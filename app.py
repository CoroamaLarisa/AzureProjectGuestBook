import os
import os
import datetime
import time

from logging import FileHandler, WARNING
from flask import Flask, render_template, request, redirect, url_for
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.storage.queue import QueueClient, BinaryBase64EncodePolicy, BinaryBase64DecodePolicy
from azure.cosmosdb.table.tableservice import TableService
from azure.cosmosdb.table.models import Entity
from typing import AnyStr, List, Dict, Tuple


app = Flask(__name__)

# Set app constants


app.config['UPLOAD_FOLDER'] = './uploads'
app.config['AZURE_STORAGE_CONNECTION_STRING'] = 'DefaultEndpointsProtocol=https;AccountName=gcccstorageguestbook;AccountKey=A7mPkaoOQ+OHPGihyYattLUSmqRTA6WCHtN/GdNq0Ag+ZfnaF+nTWQep598jSweOYE3oXgbBm27B+ASt9CqENg==;EndpointSuffix=core.windows.net'
app.config['AZURE_STORAGE_CONTAINER'] = 'images'
app.config['AZURE_STORAGE_QUEUE'] = 'thumbnailqueue'
app.config['AZURE_STORAGE_TABLE'] = 'reviews'
app.config['RECAPTCHA_ENABLED'] = False

# Set app error handling
file_handler = FileHandler('errorlog.txt')
file_handler.setLevel(WARNING)
app.logger.addHandler(file_handler)


@app.route('/')
def index():
    # Get all reviews
    message_list = get_all_reviews()

    # Render the HTML template and pass the message list to it
    return render_template('index.html', message_list=message_list[::-1])


@app.route('/upload', methods=['GET', 'POST'])
def upload():

    # if the request is of type 'GET' then we only show the upload page
    if request.method == 'GET':
        return render_template('upload.html')

    file = request.files['file']
    review = request.form['review']

    if file and review:  # check if file and review have been left
        filename = file.filename
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        thumbnail_url, full_image_url = upload_to_azure(filename)
        store_review(review, full_image_url, thumbnail_url)
        return redirect(url_for('view'))


@app.route('/view', methods=['GET'])
def view():

    # Get all reviews
    message_list = get_all_reviews()

    # Render the HTML template and pass the message list to it
    return render_template('index.html', message_list=message_list[::-1])


def get_all_reviews() -> List[Dict[AnyStr, AnyStr]]:
    """
    Get all reviews from the Azure Table defined in the app constants
    Returns:
    - message_list: List[Dict[AnyStr, AnyStr]], a list of all the messages from the table as dict, ex. [{'column_1': 'value_1','column_2': 'value_2'}]
    """
    table_service = TableService(
        connection_string=app.config['AZURE_STORAGE_CONNECTION_STRING'])

    # Retrieve values from Azure Table
    messages = table_service.query_entities(app.config['AZURE_STORAGE_TABLE'])

    # Create a list to store message details
    message_list = []

    for message in messages:
        review = message.review
        image_url = message.image_url
        thumbnail_url = message.thumbnail_url

        # Add message details to the list
        message_list.append({
            'review': review,
            'image_url': image_url,
            'thumbnail_url': thumbnail_url
        })

    return message_list


def store_review(review: AnyStr, full_image_url: AnyStr, thumbnail_url: AnyStr) -> None:
    """
    Store review in an Azure Table to be able to query the values
    Parameters:
    - review: AnyStr, the review left by the user
    - full_image_url: AnyStr, the image URL that the user will use to download the full image
    - thumbnail_url: AnyStr, the thumbnail URL that the web page will show 
    """
    table_service = TableService(
        connection_string=app.config['AZURE_STORAGE_CONNECTION_STRING'])

    new_entity = Entity()

    new_entity.PartitionKey = 'messages'
    new_entity.RowKey = str(time.time())

    new_entity.review = review
    new_entity.image_url = full_image_url
    new_entity.thumbnail_url = thumbnail_url

    table_service.insert_entity(app.config['AZURE_STORAGE_TABLE'], new_entity)


def upload_to_azure(filename: AnyStr) -> Tuple[AnyStr, AnyStr]:
    """
    Upload file by filename from the local upload folder to Azure Container as a BLOB
    Parameters:
    - filename: AnyStr, the filename of the file that will be uploaded 
    Returns:
    - thumbnail_url: AnyStr, the url of the BLOB containing the thumbnail image generated from the original image
    - full_image_download_url: AnyStr, the URL that will be used to download the original image
    """
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

    # Generate download URL for the full image
    full_image_download_url = blob_client.url + "?" + sas_token

    # Upload and generate thumbnail
    thumbnail_filename = "thumbnail_" + filename
    thumbnail_blob_client = container_client.get_blob_client(
        thumbnail_filename)

    # Store filename and thumbnail file into queue so that an Azure Function can generate the thumbnail
    generate_thumbnail_webjob(filename, thumbnail_filename)

    # Store thumbnail url
    thumbnail_url = thumbnail_blob_client.url

    return thumbnail_url, full_image_download_url


def generate_thumbnail_webjob(filename: AnyStr, thumbnail_filename: AnyStr) -> None:
    """
    Generate thumbnail by adding the original file and the thumbnail file as a message to an Azure Queue,
    which will trigger an already-defined Azure Function that will generate the thumbnail
    Parameters:
    - filename: AnyStr, the original filename
    - thumbnail_filename: the thumbnail filename
    """

    connection_string = app.config['AZURE_STORAGE_CONNECTION_STRING']
    queue_name = app.config['AZURE_STORAGE_QUEUE']

    # Connect to the thumbnail queue
    queue_client = QueueClient.from_connection_string(
        conn_str=connection_string,
        queue_name=queue_name)

    queue_client.message_encode_policy = BinaryBase64EncodePolicy()
    queue_client.message_decode_policy = BinaryBase64DecodePolicy()

    # Create a message with the filename and thumbnail filename
    message_content = {
        'filename': filename,
        'thumbnail_filename': thumbnail_filename
    }

    # Convert the message content to a string
    message_bytes = str(message_content).encode('ascii')
    queue_client.send_message(
        queue_client.message_encode_policy.encode(content=message_bytes)
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
