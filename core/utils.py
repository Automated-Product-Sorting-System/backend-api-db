import os
import shutil
import logging
from dotenv import load_dotenv
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url

# Configure logging for production environment
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables (Cloudinary SDK will automatically detect CLOUDINARY_URL)
load_dotenv()

def move_to_confirmed_dataset(local_image_path, category):
    """
    Uploads the local temporary image to Cloudinary under the specified category folder,
    deletes the local file to save server space, and returns the secure cloud URL.
    """
    try:
        # Check if the local image from the AI model actually exists
        if not local_image_path or not os.path.exists(local_image_path):
            logger.warning(f"Image not found locally at: {local_image_path}")
            return None

        # Upload the image to Cloudinary
        folder_path = f"Nexus_System/Confirmed/{category}"
        response = cloudinary.uploader.upload(
            local_image_path,
            folder=folder_path,
            unique_filename=True
        )
        
        # Remove the local temporary file from the Render server
        os.remove(local_image_path)
        logger.info(f"Successfully uploaded to Cloudinary and deleted local file: {local_image_path}")
        
        # Return the permanent secure URL to be saved in PostgreSQL
        return response.get('secure_url')
        
    except Exception as e:
        logger.error(f"Error uploading to Cloudinary: {str(e)}")
        return None

def delete_inspection_image(image_path_or_url):
    """
    Deletes the image completely. If it is still a local file, it removes it from the OS.
    If it is a Cloudinary URL, it extracts the public_id and destroys it on the cloud.
    """
    try:
        if not image_path_or_url:
            return False

        # Case 1: The image is still a local file (e.g., rejected before upload)
        if os.path.exists(image_path_or_url):
            os.remove(image_path_or_url)
            logger.info(f"Successfully deleted local file: {image_path_or_url}")
            return True
            
        # Case 2: The image is already hosted on Cloudinary
        if "cloudinary.com" in image_path_or_url:
            # Extract public_id from the Cloudinary URL
            # Example URL: https://res.cloudinary.com/cloud_name/image/upload/v12345/Folder/file.jpg
            parts = image_path_or_url.split('/upload/')
            if len(parts) == 2:
                path_with_version = parts[1]
                
                # Remove version string (e.g., v1234567890/) if present
                if path_with_version.startswith('v') and '/' in path_with_version:
                    path_without_version = path_with_version.split('/', 1)[-1]
                else:
                    path_without_version = path_with_version
                
                # Remove the file extension (.jpg, .png) to get the exact public_id
                public_id = path_without_version.rsplit('.', 1)[0]
                
                # Delete the image from Cloudinary storage
                cloudinary.uploader.destroy(public_id)
                logger.info(f"Successfully deleted from Cloudinary: {public_id}")
                return True
        
        logger.warning(f"Could not identify or find image to delete: {image_path_or_url}")
        return False
        
    except Exception as e:
        logger.error(f"Error deleting file/image: {str(e)}")
        return False