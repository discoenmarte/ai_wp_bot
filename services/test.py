import requests

def upload_file(file_path):
    url = "http://127.0.0.1:8000/extract-invoice-data/"
    try:
        with open(file_path, 'rb') as file:
            files = {'file': file}
            response = requests.post(url, files=files)

        response.raise_for_status()  # Raise an HTTPError for bad responses

        #print("Response Status Code:", response.status_code)
        ans = response.json()["cleaned_response"]
        print(ans)
        #print("Response JSON:", response.json())
    except requests.exceptions.RequestException as e:
        print("Error uploading file:", e)

if __name__ == "__main__":
    file_path = "../file-1723740297096.jpeg"  # Update this to the path of your file
    upload_file(file_path)