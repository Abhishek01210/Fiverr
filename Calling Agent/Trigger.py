import requests

response = requests.post("http://localhost:8000/initiate-calls")

print(response.json())  # Check the output
