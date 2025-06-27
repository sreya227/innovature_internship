from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# Load once
model = SentenceTransformer('all-MiniLM-L6-v2')

CATEGORIES = [
    'Food',
    'Travel',
    'Rent',
    'Bills',
    'Groceries',
    'Shopping',
    'Entertainment',
    'Health',
    'Gifts',
    'General'
]

# Precompute once
category_embeddings = model.encode(CATEGORIES)

def get_category_from_description(description):
    if not description:
        return "General"

    desc_embedding = model.encode([description])
    similarities = cosine_similarity(desc_embedding, category_embeddings)[0]
    best_index = np.argmax(similarities)
    return CATEGORIES[best_index]

