from PIL import Image
import numpy as np
from sklearn.cluster import KMeans
import os

def generate_palette(image_path, num_colors=5):
    # Validate input parameters
    if num_colors < 1:
        raise ValueError("num_colors must be at least 1")
    if num_colors > 256:
        raise ValueError("num_colors cannot exceed 256")

    # Check if file exists
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"The file {image_path} does not exist")

    # Open and process the image
    try:
        img = Image.open(image_path)
    except Exception as e:
        raise IOError(f"Error opening image: {str(e)}")

    # Convert to RGB if necessary
    if img.mode != 'RGB':
        img = img.convert('RGB')

    # Resize image to optimize performance
    width, height = img.size
    if width > 1000 or height > 1000:
        img = img.resize((1000, 1000))

    # Prepare pixel data for clustering
    pixels = np.array(img)
    pixels = pixels.reshape(-1, 3)

    # Apply K-Means clustering
    kmeans = KMeans(n_clusters=num_colors, random_state=42, n_init=10)
    kmeans.fit(pixels)

    # Get and format the palette
    palette = kmeans.cluster_centers_.astype(int)
    palette = [tuple(color) for color in palette]

    return palette

# Example usage:
if __name__ == "__main__":
    try:
        image_path = 'path_to_your_image.jpg'  # Update this path
        palette = generate_palette(image_path, num_colors=8)
        print("Generated color palette:")
        for i, color in enumerate(palette):
            print(f"Color {i+1}: RGB({color[0]}, {color[1]}, {color[2]})")
    except Exception as e:
        print(f"Error: {str(e)}")