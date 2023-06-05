import logging
import azure.functions as func
import tempfile
import ast
from azure.storage.blob import BlobServiceClient
import os
from PIL import Image
import io


def main(msg: func.QueueMessage) -> None:
    """
    An Azure Function that gets triggered every time a new message gets added to the queue, 
    and generates a thumbnail image from the one provided and stores it into an Azure BLOB
    Parameters:
    - msg: The message from the queue
    """

    # logging
    logging.info('Python queue trigger function processed a queue item: %s',
                 msg.get_body().decode('utf-8'))

    # get variables from the app configuration
    connection_string = os.environ['AzureWebJobsStorage']

    # set container name
    container_name = 'images'

    # get variables from message
    blob_name = ast.literal_eval(msg.get_body().decode('utf-8'))['filename']
    thumbnail_filename = ast.literal_eval(
        msg.get_body().decode('utf-8'))['thumbnail_filename']

    # get blob service client from connection string
    blob_service_client = BlobServiceClient.from_connection_string(
        connection_string)

    # get images container
    container_client = blob_service_client.get_container_client(container_name)

    # get original full image
    blob_client_original_image = container_client.get_blob_client(
        blob_name)  # get blob of original image
    streamdownloader = blob_client_original_image.download_blob(
    ).readall()  # get original image as bytes from blob

    # decode the bytes into an image
    image = Image.open(io.BytesIO(streamdownloader))
    image.thumbnail((200, 200))  # Adjust the size as per your requirements

    # Upload the generated thumbnail to Azure Blob Storage
    thumbnail_blob_name = thumbnail_filename
    thumbnail_blob_path = os.path.join(
        tempfile.gettempdir(), thumbnail_filename)
    image.save(thumbnail_blob_path, 'JPEG')

    # Upload the thumbnail to Azure Blob Storage
    blob_client = container_client.get_blob_client(thumbnail_blob_name)
    with open(thumbnail_blob_path, 'rb') as f:
        blob_client.upload_blob(f)

    # Delete the temporary file
    os.remove(thumbnail_blob_path)
