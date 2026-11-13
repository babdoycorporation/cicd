import sys
import os
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder
from django_pandas.io import read_frame
import joblib

# Add the project root directory to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cicd_tool.settings')

# Import Django and set up the application
import django
django.setup()

# Now import the necessary models
from pipeline.models import PipelineRun

# Extract data
queryset = PipelineRun.objects.all()
df = read_frame(queryset)

# Prepare data
# Extract datetime features from 'started_at'
df['year'] = df['started_at'].dt.year
df['month'] = df['started_at'].dt.month
df['day'] = df['started_at'].dt.day
df['hour'] = df['started_at'].dt.hour
df['minute'] = df['started_at'].dt.minute
df['second'] = df['started_at'].dt.second

# Encode categorical variables
label_encoder = LabelEncoder()
df['agent_encoded'] = label_encoder.fit_transform(df['agent'])
df['pipeline_encoded'] = label_encoder.fit_transform(df['pipeline'])

# Select relevant features
# Update the features based on the actual features you want to include
# For example, if you want to include all encoded features, you can use df[['agent_encoded', 'pipeline_encoded']]
X = df[['year', 'month', 'day', 'hour', 'minute', 'second', 'agent_encoded', 'pipeline_encoded']]
y = df['status'].apply(lambda x: 1 if x == 'failed' else 0)

# Split data into training and test sets
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train model
model = RandomForestClassifier()
model.fit(X_train, y_train)

# Save model
model_path = os.path.join(project_root, 'build_failure_predictor.pkl')
joblib.dump(model, model_path)
print(f"Model saved to {model_path}")
