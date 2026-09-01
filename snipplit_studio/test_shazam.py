import asyncio
from shazamio import Shazam

async def test():
    shazam = Shazam()
    # Recognize an existing MP3 file in downloads/music
    import glob
    files = glob.glob("downloads/music/*.mp3")
    if files:
        target = files[0]
        print("Testing Shazam on:", target)
        out = await shazam.recognize(target)
        track = out.get('track', {})
        print("RECOGNIZED TRACK TITLE:", track.get('title'))
        print("RECOGNIZED ARTIST:", track.get('subtitle'))
    else:
        print("No files to test")

asyncio.run(test())
