import schedule

def schedule_calls():
    requests.post("http://localhost:8000/outbound")

# Run every hour
schedule.every(1).hour.do(schedule_calls)

while True:
    schedule.run_pending()
    time.sleep(1)
