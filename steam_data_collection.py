# -*- coding: utf-8 -*-
"""steam_data_collection.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1X_V1tYo4HE5PP1ibWATYLJGItyduuz_y

# **Import Libraries**

We begin by importing the libraries we will be using. We start with standard library imports, or those available by default in Python, then import the third-party packages. We'll be using requests to handle interacting with the APIs, then the popular pandas and numpy libraries for handling the downloaded data.
"""

# standard library imports
import csv
import datetime as dt
import json
import os
import statistics
import time
import sys

# third-party imports
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup


# customisations - ensure tables show all columns
pd.set_option("display.max_columns", 100)

"""Next, we define a general, all-purpose function to process get requests from an API, supplied through a URL parameter. A dictionary of parameters can be supplied which is passed into the get request automatically, depending on the requirements of the API.

Rather than simply returning the response, we handle a couple of scenarios to help automation. Occasionally we encounter an SSL Error, in which case we simply wait a few seconds then try again (by recursively calling the function). When this happens, and generally throughout this project, we provide quite verbose feedback to show when these errors are encountered and how they are handled.

Sometimes there is no response when a request is made (returns None). This usually happens when too many requests are made in a short period of time, and the polling limit has been reached. We try to avoid this by pausing briefly between requests, as we'll see later, but in case we breach the polling limit we wait 10 seconds then try again.

Handling these errors in this way ensures that our function almost always returns the desired response, which we return in json format to make processing easier.
"""

def get_request(url, parameters=None):
    """Return json-formatted response of a get request using optional parameters.

    Parameters
    ----------
    url : string
    parameters : {'parameter': 'value'}
        parameters to pass as part of get request

    Returns
    -------
    json_data
        json-formatted response (dict-like)
    """
    try:
        response = requests.get(url=url, params=parameters)
    except SSLError as s:
        print('SSL Error:', s)

        for i in range(5, 0, -1):
            print('\rWaiting... ({})'.format(i), end='')
            time.sleep(1)
        print('\rRetrying.' + ' '*10)

        # recusively try again
        return get_request(url, parameters)

    if response:
        return response.json()
    else:
        # response is none usually means too many requests. Wait and try again
        print('No response, waiting 10 seconds...')
        time.sleep(10)
        print('Retrying.')
        return get_request(url, parameters)

"""# **Generate List of App IDs**

Every app on the steam store has a unique app ID. Whilst different apps can have the same name, they can't have the same ID. This will be very useful to us for identifying apps and eventually merging our tables of data.

Before we get to that, we need to generate a list of app ids which we can use to build our data sets. It's possible to generate one from the Steam API, however this has over 70,000 entries, many of which are demos and videos with no way to tell them apart. Instead, SteamSpy provides an 'all' request, supplying some information about the apps they track. It doesn't supply all information about each app, so we still need to request this information individually, but it provides a good starting point.

Because many of the return fields are strings containing commas and other punctuation, it is easiest to read the response into a pandas dataframe, and export the required appid and name fields to a csv. We could keep only the appid column as a list or pandas series, but it may be useful to keep the app name at this stage.
"""

# define the base URL and parameters
url = "https://steamspy.com/api.php"

# initialize an empty list to store data from all pages
all_data = []

# loop through all pages (0 to 79)
for page in range(1):
    parameters = {"request": "all", "page": page}
    response = requests.get(url, params=parameters)
    if response.status_code == 200:
        page_data = response.json()
        all_data.extend(page_data.values())
        sys.stdout.write(f"\rFinished fetching data for page {page}")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"\rFailed to fetch data for page {page}")
        sys.stdout.flush()

# convert the collected data into a DataFrame
steam_spy_all = pd.DataFrame(all_data)

# generate a sorted app_list from steamspy data
app_list = steam_spy_all[['appid', 'name']].sort_values('appid').reset_index(drop=True)

# save to CSV
output_path = '/content/drive/MyDrive/Colab Notebooks/data/download/app_list.csv'
app_list.to_csv(output_path, index=False)

# read from the stored CSV
app_list = pd.read_csv(output_path)

# count all items
app_list_count = len(app_list)
print(f"\nThe number of items in the dataset is: {app_list_count}")

# display first few rows
print(app_list.head())

"""# **Define Download Logic**

Now we have the app_list dataframe, we can iterate over the app IDs and request individual app data from the servers. Here we set out our logic to retrieve and process this information, then finally store the data as a csv file.

Because it takes a long time to retrieve the data, it would be dangerous to attempt it all in one go as any errors or connection time-outs could cause the loss of all our data. For this reason we define a function to download and process the requests in batches, appending each batch to an external file and keeping track of the highest index written in a separate file.

This not only provides security, allowing us to easily restart the process if an error is encountered, but also means we can complete the download across multiple sessions.

Again, we provide verbose output for rows exported, batches complete, time taken and estimated time remaining.
"""

def get_app_data(start, stop, parser, pause):
    """Return list of app data generated from parser.

    parser : function to handle request
    """
    app_data = []

    # iterate through each row of app_list, confined by start and stop
    for index, row in app_list[start:stop].iterrows():
        print('Current index: {}'.format(index), end='\r')

        appid = row['appid']
        name = row['name']

        # retrive app data for a row, handled by supplied parser, and append to list
        data = parser(appid, name)
        app_data.append(data)

        time.sleep(pause) # prevent overloading api with requests

    return app_data


def process_batches(parser, app_list, download_path, data_filename, index_filename,
                    columns, begin=0, end=-1, batchsize=100, pause=1):
    """Process app data in batches, writing directly to file.

    parser : custom function to format request
    app_list : dataframe of appid and name
    download_path : path to store data
    data_filename : filename to save app data
    index_filename : filename to store highest index written
    columns : column names for file

    Keyword arguments:

    begin : starting index (get from index_filename, default 0)
    end : index to finish (defaults to end of app_list)
    batchsize : number of apps to write in each batch (default 100)
    pause : time to wait after each api request (defualt 1)

    returns: none
    """
    print('Starting at index {}:\n'.format(begin))

    # by default, process all apps in app_list
    if end == -1:
        end = len(app_list) + 1

    # generate array of batch begin and end points
    batches = np.arange(begin, end, batchsize)
    batches = np.append(batches, end)

    apps_written = 0
    batch_times = []

    for i in range(len(batches) - 1):
        start_time = time.time()

        start = batches[i]
        stop = batches[i+1]

        app_data = get_app_data(start, stop, parser, pause)

        rel_path = os.path.join(download_path, data_filename)

        # writing app data to file
        with open(rel_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')

            for j in range(3,0,-1):
                print("\rAbout to write data, don't stop script! ({})".format(j), end='')
                time.sleep(0.5)

            writer.writerows(app_data)
            print('\rExported lines {}-{} to {}.'.format(start, stop-1, data_filename), end=' ')

        apps_written += len(app_data)

        idx_path = os.path.join(download_path, index_filename)

        # writing last index to file
        with open(idx_path, 'w') as f:
            index = stop
            print(index, file=f)

        # logging time taken
        end_time = time.time()
        time_taken = end_time - start_time

        batch_times.append(time_taken)
        mean_time = statistics.mean(batch_times)

        est_remaining = (len(batches) - i - 2) * mean_time

        remaining_td = dt.timedelta(seconds=round(est_remaining))
        time_td = dt.timedelta(seconds=round(time_taken))
        mean_td = dt.timedelta(seconds=round(mean_time))

        print('Batch {} time: {} (avg: {}, remaining: {})'.format(i, time_td, mean_td, remaining_td))

    print('\nProcessing batches complete. {} apps written'.format(apps_written))

"""Next we define some functions to handle and prepare the external files.

We use reset_index for testing and demonstration, allowing us to easily reset the index in the stored file to 0, effectively restarting the entire download process.

We define get_index to retrieve the index from file, maintaining persistence across sessions. Every time a batch of information (app data) is written to file, we write the highest index within app_data that was retrieved. As stated, this is partially for security, ensuring that if there is an error during the download we can read the index from file and continue from the end of the last successful batch. Keeping track of the index also allows us to pause the download, continuing at a later time.

Finally, the prepare_data_file function readies the csv for storing the data. If the index we retrieved is 0, it means we are either starting for the first time or starting over. In either case, we want a blank csv file with only the header row to begin writing to, se we wipe the file (by opening in write mode) and write the header. Conversely, if the index is anything other than 0, it means we already have downloaded information, and can leave the csv file alone.
"""

def reset_index(download_path, index_filename):
    """Reset index in file to 0."""
    rel_path = os.path.join(download_path, index_filename)

    with open(rel_path, 'w') as f:
        print(0, file=f)


def get_index(download_path, index_filename):
    """Retrieve index from file, returning 0 if file not found."""
    try:
        rel_path = os.path.join(download_path, index_filename)

        with open(rel_path, 'r') as f:
            index = int(f.readline())

    except FileNotFoundError:
        index = 0

    return index


def prepare_data_file(download_path, filename, index, columns):
    """Create file and write headers if index is 0."""
    if index == 0:
        rel_path = os.path.join(download_path, filename)

        with open(rel_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

"""# **Download Steam Data**

Now we are ready to start downloading data and writing to file. We define our logic particular to handling the steam API - in fact if no data is returned we return just the name and appid - then begin setting some parameters. We define the files we will write our data and index to, and the columns for the csv file. The API doesn't return every column for every app, so it is best to explicitly set these.

Next we run our functions to set up the files, and make a call to process_batches to begin the process. Some additional parameters have been added for demonstration, to constrain the download to just a few rows and smaller batches. Removing these would allow the entire download process to be repeated.
"""

def parse_steam_request(appid, name):
    """Unique parser to handle data from Steam Store API.

    Returns : json formatted data (dict-like)
    """
    url = "http://store.steampowered.com/api/appdetails/"
    parameters = {"appids": appid}

    json_data = get_request(url, parameters=parameters)
    json_app_data = json_data[str(appid)]

    if json_app_data['success']:
        data = json_app_data['data']
    else:
        data = {'name': name, 'steam_appid': appid}

    return data


# set file parameters
download_path = '/content/drive/MyDrive/Colab Notebooks/data/download'
steam_app_data = 'steam_app_data.csv'
steam_index = 'steam_index.txt'

steam_columns = [
    'type', 'name', 'steam_appid', 'required_age', 'is_free', 'controller_support',
    'dlc', 'detailed_description', 'about_the_game', 'short_description', 'fullgame',
    'supported_languages', 'header_image', 'website', 'pc_requirements', 'mac_requirements',
    'linux_requirements', 'legal_notice', 'drm_notice', 'ext_user_account_notice',
    'developers', 'publishers', 'demos', 'price_overview', 'packages', 'package_groups',
    'platforms', 'metacritic', 'reviews', 'categories', 'genres', 'screenshots',
    'movies', 'recommendations', 'achievements', 'release_date', 'support_info',
    'background', 'content_descriptors'
]

# overwrites last index for demonstration (would usually store highest index so can continue across sessions)
reset_index(download_path, steam_index)

# retrieve last index downloaded from file
index = get_index(download_path, steam_index)

# wipe or create data file and write headers if index is 0
prepare_data_file(download_path, steam_app_data, index, steam_columns)

# set end and chunksize for demonstration - remove to run through entire app list
process_batches(
    parser=parse_steam_request,
    app_list=app_list,
    download_path=download_path,
    data_filename=steam_app_data,
    index_filename=steam_index,
    columns=steam_columns,
    begin=index,
    end=10,
    batchsize=5
)

# inspect downloaded data
pd.read_csv('/content/drive/MyDrive/Colab Notebooks/data/download/steam_app_data.csv').head()

"""# **Download SteamSpy data**

To retrieve data from SteamSpy we perform a very similar process. Our parse function is a little simpler because of the how data is returned, and the maximum polling rate of this API is higher so we can set a lower value for pause in the process_batches function and download more quickly. Apart from that we set the new variables and make a call to the process_batches function once again.
"""

def parse_steamspy_request(appid, name):
    """Parser to handle SteamSpy API data."""
    url = "https://steamspy.com/api.php"
    parameters = {"request": "appdetails", "appid": appid}

    json_data = get_request(url, parameters)
    return json_data


# set files and columns
download_path = '/content/drive/MyDrive/Colab Notebooks/data/download'
steamspy_data = 'steamspy_data.csv'
steamspy_index = 'steamspy_index.txt'

steamspy_columns = [
    'appid', 'name', 'developer', 'publisher', 'score_rank', 'positive',
    'negative', 'userscore', 'owners', 'average_forever', 'average_2weeks',
    'median_forever', 'median_2weeks', 'price', 'initialprice', 'discount',
    'languages', 'genre', 'ccu', 'tags'
]

reset_index(download_path, steamspy_index)
index = get_index(download_path, steamspy_index)

# Wipe data file if index is 0
prepare_data_file(download_path, steamspy_data, index, steamspy_columns)

process_batches(
    parser=parse_steamspy_request,
    app_list=app_list,
    download_path=download_path,
    data_filename=steamspy_data,
    index_filename=steamspy_index,
    columns=steamspy_columns,
    begin=index,
    end=20,
    batchsize=5,
    pause=0.3
)

# inspect downloaded steamspy data
pd.read_csv('/content/drive/MyDrive/Colab Notebooks/data/download/steamspy_data.csv').head()

def parse_steamspy_html(appid, name):
    """Parse HTML from SteamSpy to extract followers and old userscore."""
    url = f"https://steamspy.com/app/{appid}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch data for appid {appid}. HTTP status: {response.status_code}")
            return {"appid": appid, "name": name, "followers": None, "old_userscore": None}

        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract followers count
        followers_tag = soup.find('strong', string='Followers')
        if followers_tag:
            followers_text = followers_tag.next_sibling.strip()  # Extract text after "Followers"
            followers = followers_text.lstrip(': ').replace(',', '')  # Remove leading ": " and commas
        else:
            followers = None
            print(f"Followers not found for appid {appid}")

        # Extract old userscore
        userscore_tag = soup.find('strong', string='Old userscore:')
        if userscore_tag:
            old_userscore = userscore_tag.next_sibling.strip()  # Extract text after "Old userscore:"
        else:
            old_userscore = None
            print(f"Old userscore not found for appid {appid}")

        return {
            "appid": appid,
            "name": name,
            "followers": followers,
            "old_userscore": old_userscore
        }
    except Exception as e:
        print(f"Error while processing appid {appid}: {e}")
        return {"appid": appid, "name": name, "followers": None, "old_userscore": None}

# Define the file paths and columns
download_path = '/content/drive/MyDrive/Colab Notebooks/data/download'
steamspy_extended_data = 'steamspy_data_extended.csv'
steamspy_extended_index = 'steamspy_data_extended_index.txt'
full_data_path = f"{download_path}/{steamspy_extended_data}"
index_file_path = f"{download_path}/{steamspy_extended_index}"

steamspy_extended_columns = [
    'appid', 'name', 'followers', 'old_userscore'
]

# Reset index for the extended data file
reset_index(download_path, steamspy_extended_index)
index = get_index(download_path, steamspy_extended_index)

# Prepare the file to write results
prepare_data_file(download_path, steamspy_extended_data, index, steamspy_extended_columns)

# Process and write results to the file
process_batches(
    parser=parse_steamspy_html,
    app_list=app_list,
    download_path=download_path,
    data_filename=steamspy_extended_data,
    index_filename=steamspy_extended_index,
    columns=steamspy_extended_columns,
    begin=index,
    end=20,  # Adjust as needed
    batchsize=5,
    pause=0.3
)

# inspect downloaded steamspy data
pd.read_csv('/content/drive/MyDrive/Colab Notebooks/data/download/steamspy_data_extended.csv').head()

"""# **Download Steamcharts Data**"""

def parse_steamcharts_html(appid, name):
    """
    Parse HTML from SteamCharts to extract 24-hour peak, all-time peak,
    and the all-time peak date based on the Peak Players table.
    """
    url = f"https://steamcharts.com/app/{appid}"
    try:
        response = requests.get(url)
        if response.status_code != 200:
            print(f"Failed to fetch data for appid {appid}. HTTP status: {response.status_code}")
            return {"appid": appid, "name": name, "24-hour peak": None, "all-time peak": None, "all-time peak date": None}

        # Parse the HTML content
        soup = BeautifulSoup(response.text, 'html.parser')

        # Extract 24-hour peak
        peak_24h_tag = soup.find('div', class_='app-stat').find_next('div', class_='app-stat')
        peak_24h = peak_24h_tag.find('span', class_='num').text.replace(',', '') if peak_24h_tag else None

        # Extract all-time peak
        all_time_peak_tag = peak_24h_tag.find_next('div', class_='app-stat') if peak_24h_tag else None
        all_time_peak = all_time_peak_tag.find('span', class_='num').text.replace(',', '') if all_time_peak_tag else None

        # Extract all-time peak date
        all_time_peak_date = None
        if all_time_peak:
            peak_players_table = soup.find('table', class_='common-table')
            if peak_players_table:
                rows = peak_players_table.find_all('tr')
                for row in rows:
                    # Find the row with the matching all-time peak value
                    cells = row.find_all('td')
                    if len(cells) > 4:
                        peak_value = cells[4].text.replace(',', '').strip()
                        if peak_value == all_time_peak:
                            all_time_peak_date = cells[0].text.strip()
                            break

        return {
            "appid": appid,
            "name": name,
            "24-hour peak": peak_24h,
            "all-time peak": all_time_peak,
            "all-time peak date": all_time_peak_date,
        }
    except Exception as e:
        print(f"Error while processing appid {appid}: {e}")
        return {"appid": appid, "name": name, "24-hour peak": None, "all-time peak": None, "all-time peak date": None}

# Set files and columns
download_path = '/content/drive/MyDrive/Colab Notebooks/data/download'
steamcharts_data = 'steamcharts_data.csv'
steamcharts_index = 'steamcharts_index.txt'

steamcharts_columns = [
    'appid', 'name', '24-hour peak', 'all-time peak', 'all-time peak date'
]

# Reset index for the SteamCharts data file
reset_index(download_path, steamcharts_index)
index = get_index(download_path, steamcharts_index)

# Prepare the file to write results
prepare_data_file(download_path, steamcharts_data, index, steamcharts_columns)

# Process and write results to the file
process_batches(
    parser=parse_steamcharts_html,
    app_list=app_list,
    download_path=download_path,
    data_filename=steamcharts_data,
    index_filename=steamcharts_index,
    columns=steamcharts_columns,
    begin=index,
    end=20,  # Adjust as needed
    batchsize=5,
    pause=0.3
)

# inspect downloaded steamcharts data
pd.read_csv('/content/drive/MyDrive/Colab Notebooks/data/download/steamcharts_data.csv').head()