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

def extract_public_id(image_url):
    """Helper to extract the public_id from a Cloudinary URL so we can move or delete it"""
    try:
        parts = image_url.split('/upload/')
        if len(parts) == 2:
            path_with_version = parts[1]
            if path_with_version.startswith('v') and '/' in path_with_version:
                path_without_version = path_with_version.split('/', 1)[-1]
            else:
                path_without_version = path_with_version
            
            # Extract the public_id by removing the file extension since Cloudinary works with the asset name only
            public_id = path_without_version.rsplit('.', 1)[0]
            return public_id
        return None
    except Exception:
        return None

def upload_image(image_bytes, folder="Nexus_System/Pending"):
    """Uploads the image directly from memory to the cloud (runs in the background)"""
    try:
        response = cloudinary.uploader.upload(
            image_bytes,
            folder=folder,
            unique_filename=True
        )
        logger.info("Successfully uploaded image bytes to Cloudinary (Pending).")
        return response.get('secure_url')
    except Exception as e:
        logger.error(f"Error uploading bytes to Cloudinary: {str(e)}")
        return None

def move_cloudinary_asset(image_url, new_category):
    """Moves the image within Cloudinary's servers from the pending path to the confirmed path"""
    try:
        if not image_url or "cloudinary.com" not in image_url:
            return None

        old_public_id = extract_public_id(image_url)
        if not old_public_id:
            return None

        # Extract the filename and prepare the new path
        filename = old_public_id.split('/')[-1]
        new_public_id = f"Nexus_System/Confirmed/{new_category}/{filename}"
        
        # Command to move the asset
        response = cloudinary.uploader.rename(old_public_id, new_public_id)
        logger.info(f"Successfully moved image to: {new_public_id}")
        return response.get('secure_url')
        
    except Exception as e:
        logger.error(f"Error moving asset in Cloudinary: {str(e)}")
        return None

def delete_cloudinary_asset(image_url):
    """Deletes the image permanently from Cloudinary to save space"""
    try:
        if not image_url or "cloudinary.com" not in image_url:
            return False

        public_id = extract_public_id(image_url)
        if public_id:
            cloudinary.uploader.destroy(public_id)
            logger.info(f"Successfully deleted from Cloudinary: {public_id}")
            return True
        return False
        
    except Exception as e:
        logger.error(f"Error deleting from Cloudinary: {str(e)}")
        return False