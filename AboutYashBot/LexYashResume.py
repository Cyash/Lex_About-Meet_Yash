from __future__ import print_function
import math
import dateutil.parser
import datetime
from datetime import datetime as eventtime
import time
import logging
import os
import boto3
from botocore.exceptions import ClientError
import urllib2
import json
import pymssql


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

""" --- Helpers to build responses which match the structure of the necessary dialog actions --- """

def get_slots(intent_request):
    return intent_request['currentIntent']['slots']

def elicit_slot(session_attributes, intent_name, slots, slot_to_elicit, message):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'ElicitSlot',
            'intentName': intent_name,
            'slots': slots,
            'slotToElicit': slot_to_elicit,
            'message': message
        }
    }


def close(session_attributes, fulfillment_state, message):
    response = {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Close',
            'fulfillmentState': fulfillment_state,
            'message': message
        }
    }

    return response


def delegate(session_attributes, slots):
    return {
        'sessionAttributes': session_attributes,
        'dialogAction': {
            'type': 'Delegate',
            'slots': slots
        }
    }

""" --- Helper Functions --- """

def parse_int(n):
    try:
        return int(n)
    except ValueError:
        return float('nan')


def build_validation_result(is_valid, violated_slot, message_content):
    if message_content is None:
        return {
            "isValid": is_valid,
            "violatedSlot": violated_slot,
        }

    return {
        'isValid': is_valid,
        'violatedSlot': violated_slot,
        'message': {'contentType': 'PlainText', 'content': message_content}
    }


def isvalid_date(date):
    try:
        dateutil.parser.parse(date)
        return True
    except ValueError:
        return False


def validate_meet_request(agenda, date, time, User):
    
    agenda_types = ['skills', 'experience', 'background']
    if agenda is not None and agenda.lower() not in agenda_types:
        return build_validation_result(False,
                                       'MeetupAgenda',
                                       'I dont want to talk about {} , would like to talk about something else, how about to talk about my skills/ experience or about my background?'.format(agenda))
    
    '''pattern = r"\"?([-a-zA-Z0-9.`?{}]+@\w+\.\w+)\"?"
    if not re.match(pattern, User):
        return build_validation_result(False,
                                       'MeetupUser',
                                       'not a valid email format, please provide valid email')
    '''
    if date is not None:
        if not isvalid_date(date):
            return build_validation_result(False, 'MeetupDate', 'I did not understand that, what date would you like to meet?')
        elif datetime.datetime.strptime(date, '%Y-%m-%d').date() <= datetime.date.today():
            return build_validation_result(False, 'MeetupDate', 'You can meet up from tomorrow onwards.  What day would you like to meet up?')

    if time is not None:
        if len(time) != 5:
            # Not a valid time; use a prompt defined on the build-time model.
            return build_validation_result(False, 'MeetupTime', None)

        hour, minute = time.split(':')
        hour = parse_int(hour)
        minute = parse_int(minute)
        if math.isnan(hour) or math.isnan(minute):
            # Not a valid time; use a prompt defined on the build-time model.
            return build_validation_result(False, 'MeetupTime', None)

        if hour < 16:
            # Outside of business hours
            return build_validation_result(False, 'MeetupTime', 'I wont available on business hours. Can you specify a time outside of this range?')

    return build_validation_result(True, None, None)


""" --- Functions that control the bot's behavior --- """

def About_Yash(intent_request):

    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': 'A versatile character, engineer by passion, creative in nature and a strong believer in evaluating and challenging paradigms.'})

def Google_Search(intent_request):
    urls = []
    query = get_slots(intent_request)['Query']
    logger.debug(query)
    
    url = ('https://www.googleapis.com/customsearch/v1?'
           'key=%s'
           '&cx=%s'
           '&alt=json'
           '&num=3'
           '&q=%s') % (os.environ['API_KEY'], os.environ['CX'], query)

    logger.debug(url)
    request = urllib2.Request(url)
    data = urllib2.urlopen(request)
    data = json.load(data)


    for url in data['items']:
        urls.append(url['link'])
        
    urls = json.dumps(urls)

    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': urls})


def Meet_Yash(intent_request):
    
    Date = get_slots(intent_request)["MeetupDate"]
    Time = get_slots(intent_request)["MeetupTime"]
    User = get_slots(intent_request)["MeetupUser"]
    Agenda = get_slots(intent_request)["MeetupAgenda"]

    source = intent_request['invocationSource']
    if source == 'DialogCodeHook':
        slots = get_slots(intent_request)
        validation_result = validate_meet_request(Agenda, Date, Time, User)
        if not validation_result['isValid']:
            slots[validation_result['violatedSlot']] = None
            return elicit_slot(intent_request['sessionAttributes'],
                               intent_request['currentIntent']['name'],
                               slots,
                               validation_result['violatedSlot'],
                               validation_result['message'])
        
        output_session_attributes = intent_request['sessionAttributes'] if intent_request['sessionAttributes'] is not None else {}
        
        if Agenda is not None and Time is not None and Date is not None and User is not None:
            output_session_attributes['MeetupAgenda'] = Agenda
            output_session_attributes['MeetupTime'] = Time
            output_session_attributes['MeetupDate'] = Date
            output_session_attributes['MeetupUser'] = User
            
        return delegate(output_session_attributes, get_slots(intent_request))
        
        
    logger.debug('calling SES to send Email')
    SendEventInvite(Date, Time, User)
    InsertToDB(Date, Time, User, Agenda)
    return close(intent_request['sessionAttributes'],
                     'Fulfilled',
                     {'contentType': 'PlainText',
                      'content': 'Thanks, your request for meeting yash has been recieved'})
                          

def About_Yash_skills(intent_request):
    return close(intent_request['sessionAttributes'],
                 'Fulfilled',
                 {'contentType': 'PlainText',
                  'content': 'Yash is very good at Python, Java, Scala and comfortable with bigdata tools such as Apache Spark he loves Implementing microservices using AWS. He has recently delivered a project on machine Learning'})


""" --- SendMailEvent--- """

def SendEventInvite(Date, Time, User):
    SENDER = "os.environ['SENDER']"

    RECIPIENT = "os.environ['RECIPIENT']"

    SUBJECT = "Lets have a chat!"

    BODY_TEXT = (
        "you've received a request from {} to have a chat on {} at {}!".format(User, Date, Time )
    )

    CHARSET = "UTF-8"

    # Create a new SES resource and specify a region.
    client = boto3.client('ses')

    try:
        response = client.send_email(
            Destination={
                'ToAddresses': [
                    RECIPIENT,
                ],
            },
            Message={
                'Body': {
                    'Text': {
                        'Charset': CHARSET,
                        'Data': BODY_TEXT,
                    },
                },
                'Subject': {
                    'Charset': CHARSET,
                    'Data': SUBJECT,
                },
            },
            Source=SENDER,
        )
    # Display an error if something goes wrong.
    except ClientError as e:
        print(e.response['Error']['Message'])
    else:
        print("Email sent! Message ID:"),
        print(response['ResponseMetadata']['RequestId'])

""" --- DB Event --- """        

def InsertToDB(Date, Time, User, Agenda):
    logger.debug("connection to sandbox")
    cnx = pymssql.connect(
      server='sandboxdb.cz9nzsfpnod7.us-east-1.rds.amazonaws.com', 
      user= os.environ['USER'],
      password= os.environ['PASSWORD'],
      database=os.environ['DB'],
      autocommit=True
    )
    args = [Date, Time, User, Agenda]
    
    cursorLex = cnx.cursor()
    logger.debug("inserting starts. args=%s" % (args))
    cursorLex.execute('''insert into chatRequests (Date, Time, email, Agenda) VALUES (%s, %s, %s, %s)''', tuple(args))



""" --- Intents --- """

def dispatch(intent_request):
    """
    Called when the user specifies an intent for this bot.
    """

    logger.debug('dispatch userId={}, intentName={}'.format(intent_request['userId'], intent_request['currentIntent']['name']))

    intent_name = intent_request['currentIntent']['name']
    print(intent_name)
    # Dispatch to your bot's intent handlers
    if intent_name == 'AboutYash':
        return About_Yash(intent_request)
    if intent_name == 'AboutYashSkills':
        return About_Yash_skills(intent_request)
    if intent_name == 'MeetYash':
        return Meet_Yash(intent_request)
    if intent_name == 'GoogleSearch':
        return Google_Search(intent_request)    

    raise Exception('Intent with name ' + intent_name + ' not supported')


""" --- Main handler --- """

def lambda_handler(event, context):
    """
    Route the incoming request based on intent.
    The JSON body of the request is provided in the event slot.
    """
    # By default, treat the user request as coming from the America/New_York time zone.
    os.environ['TZ'] = 'America/New_York'
    time.tzset()
    logger.debug('event.bot.name={}'.format(event['bot']['name']))

    return dispatch(event)

