import os
import tempfile
from PIL import Image
import azure.functions as func
from azure.storage.blob import BlobServiceClient, BlobClient

def main(msg: func.QueueMessage) -> None:
    image_data = msg.get_body()
    thumbnail_filename = msg.id

    # Generate thumbnail using PIL library
    with tempfile.NamedTemporaryFile(suffix='.jpg') as temp_image:
        with open(temp_image.name, 'wb') as f:
            f.write(image_data)
        image = Image.open(temp_image.name)
        image.thumbnail((200, 200))  # Adjust the size as per your requirements

        # Upload the generated thumbnail to Azure Blob Storage
        connection_string = os.environ['AzureWebJobsStorage']
        container_name = '<your-container-name>'
        thumbnail_blob_name = 'thumbnail_' + thumbnail_filename
        thumbnail_blob_path = os.path.join(tempfile.gettempdir(), thumbnail_blob_name)
        image.save(thumbnail_blob_path, 'JPEG')

        # Upload the thumbnail to Azure Blob Storage
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)
        blob_client = container_client.get_blob_client(thumbnail_blob_name)
        with open(thumbnail_blob_path, 'rb') as f:
            blob_client.upload_blob(f)

    # Delete the temporary file
    os.remove(thumbnail_blob_path)