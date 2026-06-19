import sounddevice as sd

for i, device in enumerate(sd.query_devices()):
    print(i, device["name"])
    