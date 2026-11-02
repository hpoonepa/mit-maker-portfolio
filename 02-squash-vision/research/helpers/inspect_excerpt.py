from pathlib import Path
import sys

import av
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parent
sheet = Image.new("RGB", (1280, 800), "#111111")
draw = ImageDraw.Draw(sheet)
with av.open(str(root / "source-match.mp4")) as container:
    stream = container.streams.video[0]
    for index, seconds in enumerate(int(value) for value in sys.argv[1:]):
        container.seek(int(seconds / stream.time_base), stream=stream)
        for frame in container.decode(stream):
            if frame.time is not None and frame.time >= seconds:
                frame.to_image().save(root / f"source-{seconds}s.jpg")
                preview = frame.to_image().resize((426, 240))
                x, y = (index % 3) * 426, (index // 3) * 266
                sheet.paste(preview, (x, y))
                draw.text((x + 8, y + 245), f"{seconds}s", fill="white")
                break
sheet.save(root / "excerpt-contact-sheet.jpg")
