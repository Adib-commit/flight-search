# Flights Search — Background Service

The app runs as a **systemd service** (`flights-search`) that starts automatically on boot and logs to `logs/app.log`.

---

## Start / Stop / Restart

```bash
# Enable to start on boot (one-time setup)
sudo systemctl enable flights-search

# Start the service
sudo systemctl start flights-search

# Stop the service
sudo systemctl stop flights-search

# Restart the service
sudo systemctl restart flights-search

# Check status
sudo systemctl status flights-search
```

---

## Trace Logs

```bash
# Follow live log output
tail -f /root/personal/flights_search/logs/app.log

# View last 100 lines
tail -100 /root/personal/flights_search/logs/app.log

# Search for errors
grep -i error /root/personal/flights_search/logs/app.log

# Or use journalctl (systemd journal)
sudo journalctl -u flights-search -f
```

---

## Service File Location

```
/etc/systemd/system/flights-search.service
```

After editing the service file, reload the daemon:

```bash
sudo systemctl daemon-reload
sudo systemctl restart flights-search
```

---

## App URL

```
http://localhost:8000
```
