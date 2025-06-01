with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# remove non-breaking spaces (U+00A0)
content = content.replace('\u00A0', ' ')

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
