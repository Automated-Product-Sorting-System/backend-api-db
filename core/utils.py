import os
import shutil
import logging
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Read paths from .env file with fallback values if variables are not found
PROJECT_BASE_PATH = os.getenv("PROJECT_BASE_PATH", "Grad_Proj/")
CONFIRMED_DATASET_PATH = os.getenv("CONFIRMED_DATASET_PATH", "confirmed_dataset")

def move_to_confirmed_dataset(local_image_path, category):
    """
    Moves an image to the confirmed dataset directory based on its category.
    """
    # Clean the path based on the environment variable
    clean_path = local_image_path.replace(PROJECT_BASE_PATH, "").lstrip("/")
    
    target_dir = os.path.join(CONFIRMED_DATASET_PATH, category)
    os.makedirs(target_dir, exist_ok=True)
    
    file_name = os.path.basename(clean_path)
    target_path = os.path.join(target_dir, file_name)

    try:
        if os.path.exists(clean_path):
            shutil.move(clean_path, target_path)
            logger.info(f"Moved: {file_name} to {category}")
            return target_path
        else:
            logger.warning(f"Not Found: {clean_path} (Current Dir: {os.getcwd()})")
            return None
    except Exception as e:
        logger.error(f"Error moving file: {e}")
        return None
    
def delete_inspection_image(image_path):
    """
    Deletes an image from the system completely.
    """
    try:
        clean_path = image_path.replace(PROJECT_BASE_PATH, "").lstrip("/")
        
        if os.path.exists(clean_path):
            os.remove(clean_path)
            logger.info(f"Successfully deleted: {clean_path}")
            return True
        else:
            logger.warning(f"Cannot delete: File not found at {clean_path}")
            return False
    except Exception as e:
        logger.error(f"Error deleting file: {e}")
        return False