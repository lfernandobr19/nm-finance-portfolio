import pathlib

p = pathlib.Path(".env")
text = p.read_text() if p.exists() else ""


def setvar(key, value):
    global text
    out = []
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith(key + "=") or s == key:
            continue
        out.append(ln)
    out.append(f"{key}={value}")
    text = "\n".join(out).strip() + "\n"


setvar("FCM_PROJECT_ID", "raven---nm-finance")
setvar(
    "FCM_SERVICE_ACCOUNT_JSON",
    "/home/<USER>/Projects/fiidesk/backend/.secrets/firebase-adminsdk.json",
)
p.write_text(text)

for ln in text.splitlines():
    if ln.startswith("FCM_"):
        k = ln.split("=", 1)[0]
        v = "<path>" if "SERVICE_ACCOUNT" in k else ln.split("=", 1)[1]
        print(f"{k}={v}")
