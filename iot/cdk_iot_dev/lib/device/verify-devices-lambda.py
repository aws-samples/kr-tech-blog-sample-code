import json
import logging
import sys

# Configure logging
logger = logging.getLogger()

for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)

FORMAT = "[%(asctime)s - %(levelname)s - %(filename)s:%(lineno)s - %(funcName)s - %(message)s"
h.setFormatter(logging.Formatter(FORMAT))

logger.addHandler(h)
logger.setLevel(logging.INFO)

SERIAL_STARTSWITH = "297468"


def verify_serial(serial_number):
    if serial_number.startswith(SERIAL_STARTSWITH):
        logger.info("serial_number {} verification succeeded - starts with {}".format(serial_number, SERIAL_STARTSWITH))
        return True
        
    logger.error("serial_number {} verification failed - does not start with {}".format(serial_number, SERIAL_STARTSWITH))
    return False
    

def lambda_handler(event, context):
    response = {'allowProvisioning': False}
    logger.info("event: {}".format(json.dumps(event, indent=2)))

    if not "SerialNumber" in event["parameters"]:
        logger.error("SerialNumber not provided")
    else:
        serial_number = event["parameters"]["SerialNumber"]
        if verify_serial(serial_number):
            response = {'allowProvisioning': True}
    
    logger.info("response: {}".format(response))
    return response
