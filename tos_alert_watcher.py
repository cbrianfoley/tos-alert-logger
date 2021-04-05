#!/usr/bin/env python3.8
import os
import re
import csv
import time
from tda import auth
from tda.client import Client
from selenium import webdriver
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from datetime import datetime

# This script monitors a gmail account for TDA alerts, and upon getting an email, retrieves instrument data and logs to a file

# USAGE:
# --------------------------------
# STEP ONE:
# --------------------------------
# Install requirements by using the command:
# python -m pip install -r requirements.txt
# --------------------------------
# STEP TWO: GIVE THIS SCRIPT PERMISSION TO READ GMAIL:
# --------------------------------
# Enable the gmail API and make a 'Desktop App' (using the link below, the app will be called 'Quickstart' by default):
# https://developers.google.com/gmail/api/quickstart/python
# place the downloadable 'credentials.json' file in the same folder as this script 
# (keep this credentials.json file safe - anyone who has it has access to your email account)
# when you run this script, it will require you to sign in and give this script (your 'app') permission to read/modify your mail
# the script will maintain a file 'gmailtoken.json' so you don't have to log in again
# --------------------------------
# STEP THREE: GIVE THIS SCRIPT PERMISSION TO GET TDA DATA:
# --------------------------------
# Similar to gmail, we have to make a TDA app, however there is a couple extra steps...
# Make a TDA Developer account (which will be separate from your brokerage username/password) here:
# https://developer.tdameritrade.com/
# see here if you need help: https://developer.tdameritrade.com/content/getting-started
# create an app and use the Redirect/Callback URI 'http://localhost' 
# copy/paste the API_KEY and REDIRECT_URI from the app into this script below (exact spelling matters - if you put a trailing '/', for example, be sure it matches)
API_KEY = 'YOURAPIKEY@AMER.OAUTHAP'
REDIRECT_URI = 'http://localhost'
ACCOUNT_ID = '123456789' # your account ID is the 9 digit number visible at the top when logged into TOS desktop
# --------------------------------
# STEP FOUR: TDA AUTH IS STUPID AND GETTING AN OAUTH TOKEN IS COMPLICATED SO DO THIS:
# --------------------------------
# Install the IIS service by:
#   1. press Win+R and typing 'appwiz.cpl' (no quotes) and click OK
#       2. then click 'Turn Windows Features On/Off'
#           3. then check the checkbox 'Internet Information Services' (it might be a square that fills the box, not a checkmark, and that's fine) and click OK
# IIS will install. If you go to the website http://localhost and get a blue IIS page, you did it right 
# once this script runs for the first time and you get a tdatoken.pickle file, you can (and should) uninstall the IIS service by unchecking the box you checked earlier
# similar to the gmail API, once we have the file 'tdatoken.pickle', this script will maintain it so we won't have to log in again
# --------------------------------
# STEP FIVE: Run the script. Any alerts that come into your email will be found, parsed, and data will be sent to a file
# --------------------------------
# 'python .\tos_alert_watcher.py'

# -------------------------------
# The body of the script starts now
# -------------------------------
FILE = datetime.now().strftime('%Y%m%d') + '.csv'

def parse_instrument_from_email(message):
    # parsing stupid tda api formats
    # expected output is 'SPY_mmddyyC390'
    # multiple can be provided if separated by commas
    # message format 'Alert: New symbols: .FB210401C292.5, .MRVL210416C54, .DERP210416C69 was added to TheAve'
    parsed = ''
    message=message+'END'
    messagesplit = message.split(' ')
    for word in messagesplit:
        if word[0] == '.':
            instrument = word.replace(',','')
            splitinstrument = instrument.split('C')
            contractstrike = splitinstrument[-1]
            contractexpiry = re.findall(r'\d+',instrument)
            expyear = contractexpiry[0][0:2]
            expmonth = contractexpiry[0][2:4]
            expday = contractexpiry[0][4:6]
            contractsymbol = re.findall(r'\D+',instrument)
            contractsymbol[0] = contractsymbol[0].replace('.','')
            parsed = parsed+contractsymbol[0]+'_'+expmonth+expday+expyear+'C'+contractstrike+' '
    if len(parsed.split(' ')) > 2:
        parsed = parsed.replace(' ',',')
        parsed = parsed[:-1]
    return parsed # one or more separated by commas

def log_data(quote):
    print('Logging to file...')
    quote = quote.json()
    with open(FILE,'a',newline='') as f:
        wr = csv.writer(f, dialect='excel')
        for q in quote:
            symbol = quote[q]['underlying']
            expdate = str(quote[q]['expirationYear']) + '/' + str(quote[q]['expirationMonth']) + '/' + str(quote[q]['expirationDay'])
            strike = quote[q]['strikePrice']
            bid = quote[q]['bidPrice']
            ask = quote[q]['askPrice']
            vol = quote[q]['volatility']
            lastPrice = quote[q]['lastPrice']
            dataObtained = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            wr.writerow([symbol,expdate,strike,bid,ask,lastPrice,vol,dataObtained])

def main():
    print('Script start time: ' + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    # Get our log file and make headers
    with open(FILE,'a',newline='') as f:
        wr = csv.writer(f, dialect='excel')
        wr.writerow(['symbol','expdate','strike','bid','ask','lastPrice','volatility','dataObtained'])

    # Auth with gmail and make token if not already existing
    SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
    creds = None
    if os.path.exists('gmailtoken.json'):
        creds = Credentials.from_authorized_user_file('gmailtoken.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('gmailtoken.json', 'w') as token:
            token.write(creds.to_json())
    service = build('gmail', 'v1', credentials=creds)

    # Auth with tda and make token if not already existing
    try:
        c = auth.client_from_token_file('tdatoken.pickle', API_KEY)
    except FileNotFoundError:
        with webdriver.Chrome() as driver:
            c = auth.client_from_login_flow(driver, API_KEY, REDIRECT_URI, 'tdatoken.pickle')

    # Calls the Gmail API every 5 minutes
    while True:
        instruments = []
        print('Checking for unread alerts@thinkorswim.com emails')
        messages = service.users().messages().list(userId='me', q='is:UNREAD from:alerts@thinkorswim.com').execute().get('messages', [])
        if not messages:
            print('None found.')
        else:
            print('Message(s) found:')
            for message in messages:
                msg = service.users().messages().get(userId='me', id=message['id']).execute()
                print(msg['snippet'][0:60]+'[...]')
                service.users().messages().modify(userId='me', id=message['id'],body={'removeLabelIds': ['UNREAD']}).execute()
                print('Message marked as read')
                instruments.append(parse_instrument_from_email(msg['snippet']))
                print(instruments)
            quote = c.get_quotes(symbols=instruments)
            assert quote.status_code == 200, quote.raise_for_status()
            log_data(quote)
        print('Waiting 5 minutes...')
        print('Press Ctrl+C to end this script')
        time.sleep(300)

if __name__ == "__main__":
    main()