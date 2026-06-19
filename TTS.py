import csv
from pathlib import Path

import boto3

REGION = "eu-north-1"  # e.g., us-east-1, us-west-2


def load_aws_credentials():
    credentials_path = Path(__file__).with_name("rootkey.csv")

    with credentials_path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        row = next(reader)

    return row["Access key ID"], row["Secret access key"]


aws_access_key_id, aws_secret_access_key = load_aws_credentials()

# Create a Polly client
polly_client = boto3.client(
    "polly",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    region_name=REGION
)

# Text to convert to speech
text_to_speak = "Hello! This is a test using Amazon Polly."

# Synthesize speech
response = polly_client.synthesize_speech(
    Text=text_to_speak,
    OutputFormat="mp3",  # You can also use "pcm" or "ogg_vorbis"
    VoiceId="Justin"     # Change voice as desired
)

# Save audio to file
with open("speech.OGG", "wb") as file:
    file.write(response["AudioStream"].read())

print("Speech saved to speech.OGG")
