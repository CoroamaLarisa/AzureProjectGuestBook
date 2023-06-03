from flask import Flask, render_template, url_for, redirect
from logging import FileHandler, WARNING
from pathlib import Path
import sqlite3 as sql
import os


from flask import Flask, render_template, request, redirect, url_for
from azure.storage.blob import BlobServiceClient, BlobClient, generate_blob_sas, BlobSasPermissions
from azure.servicebus import ServiceBusClient, ServiceBusMessage

import os
import datetime


file_handler = FileHandler('errorlog.txt')
file_handler.setLevel(WARNING)

app = Flask(__name__)


app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['AZURE_STORAGE_CONNECTION_STRING'] = 'DefaultEndpointsProtocol=https;AccountName=gcccstorageguestbook;AccountKey=A7mPkaoOQ+OHPGihyYattLUSmqRTA6WCHtN/GdNq0Ag+ZfnaF+nTWQep598jSweOYE3oXgbBm27B+ASt9CqENg==;EndpointSuffix=core.windows.net'
app.config['AZURE_STORAGE_CONTAINER'] = 'images'
app.config['AZURE_STORAGE_QUEUE'] = 'thumbnailqueue'

# ToDo replace this with your secret key
app.config['SECRET_KEY'] = 'your secret key goes here'
# app.config['RECAPTCHA_PUBLIC_KEY'] = 'your public key goes here' #ToDo replace this with your private key
# app.config['RECAPTCHA_PRIVATE_KEY'] = 'your private key goes here' #ToDo replace this with your private key
app.config['RECAPTCHA_ENABLED'] = False

app.logger.addHandler(file_handler)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['file']
    review = request.form['review']
    if file and review:
        filename = file.filename
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        thumbnail_url, full_image_url = upload_to_azure(filename)
        return render_template('success.html', thumbnail_url=thumbnail_url, full_image_url=full_image_url, review=review)
    return redirect(url_for('index'))


def upload_to_azure(filename):
    connection_string = app.config['AZURE_STORAGE_CONNECTION_STRING']
    container_name = app.config['AZURE_STORAGE_CONTAINER']

    blob_service_client = BlobServiceClient.from_connection_string(
        connection_string)
    container_client = blob_service_client.get_container_client(container_name)

    # Upload full-size image
    blob_client = container_client.get_blob_client(filename)
    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "rb") as data:
        blob_client.upload_blob(data)

    # Generate SAS token for the full-size image
    sas_token = generate_blob_sas(
        account_name=blob_service_client.account_name,
        container_name=container_name,
        blob_name=filename,
        account_key=blob_service_client.credential.account_key,
        permission=BlobSasPermissions(read=True),
        start=datetime.datetime.utcnow(),
        expiry=datetime.datetime.utcnow() + datetime.timedelta(days=1)
    )

    full_image_url = blob_client.url + "?" + sas_token

    # Upload and generate thumbnail
    thumbnail_filename = "thumbnail_" + filename
    thumbnail_blob_client = container_client.get_blob_client(
        thumbnail_filename)
    with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), "rb") as data:
        image_data = data.read()

    # Generate thumbnail using Azure WebJob worker
    generate_thumbnail_webjob(image_data, thumbnail_filename)

    thumbnail_url = thumbnail_blob_client.url

    return thumbnail_url, full_image_url


def generate_thumbnail_webjob(image_data, thumbnail_filename):
    
    connection_string = app.config['AZURE_STORAGE_CONNECTION_STRING']

    servicebus_client = ServiceBusClient.from_connection_string(
        connection_string)
    sender = servicebus_client.get_queue_sender(
        app.config['AZURE_STORAGE_QUEUE'])

    message = ServiceBusMessage(body=image_data, subject=thumbnail_filename)
    sender.send_messages(message)

    sender.close()
    servicebus_client.close()


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
