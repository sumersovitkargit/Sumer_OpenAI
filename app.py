import enum
import json
import os
import base64
import requests
from flask import Flask, request, render_template, jsonify
from werkzeug.utils import secure_filename
from typing import Union


# Define Enum classes
class MediaType(enum.Enum):
    Text = 1
    Image = 2


class Category(enum.Enum):
    Hate = 1
    SelfHarm = 2
    Sexual = 3
    Violence = 4


class Action(enum.Enum):
    Accept = 1
    Reject = 2


# Define exception for detection error
class DetectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"DetectionError(code={self.code}, message={self.message})"


# Define Decision object to store action results
class Decision(object):
    def __init__(self, suggested_action: Action, action_by_category: dict[Category, Action]) -> None:
        self.suggested_action = suggested_action
        self.action_by_category = action_by_category


# Define ContentSafety class to interact with Azure API
class ContentSafety(object):
    def __init__(self, endpoint: str, subscription_key: str, api_version: str) -> None:
        self.endpoint = endpoint
        self.subscription_key = subscription_key
        self.api_version = api_version

    def build_url(self, media_type: MediaType) -> str:
        if media_type == MediaType.Text:
            return f"{self.endpoint}/contentsafety/text:analyze?api-version={self.api_version}"
        elif media_type == MediaType.Image:
            return f"{self.endpoint}/contentsafety/image:analyze?api-version={self.api_version}"
        else:
            raise ValueError(f"Invalid Media Type {media_type}")

    def build_headers(self) -> dict[str, str]:
        return {
            "Ocp-Apim-Subscription-Key": self.subscription_key,
            "Content-Type": "application/json",
        }

    def build_request_body(self, media_type: MediaType, content: str) -> dict:
        if media_type == MediaType.Text:
            return {"text": content}
        elif media_type == MediaType.Image:
            return {"image": {"content": content}}
        else:
            raise ValueError(f"Invalid Media Type {media_type}")

    def detect(self, media_type: MediaType, content: str) -> dict:
        url = self.build_url(media_type)
        headers = self.build_headers()
        request_body = self.build_request_body(media_type, content)
        payload = json.dumps(request_body)

        response = requests.post(url, headers=headers, data=payload)
        res_content = response.json()

        if response.status_code != 200:
            raise DetectionError(res_content["error"]["code"], res_content["error"]["message"])

        return res_content

    def get_detect_result_by_category(self, category: Category, detect_result: dict) -> Union[int, None]:
        category_res = detect_result.get("categoriesAnalysis", None)
        for res in category_res:
            if category.name == res.get("category", None):
                return res
        raise ValueError(f"Invalid Category {category}")

    def make_decision(self, detection_result: dict, reject_thresholds: dict[Category, int]) -> Decision:
        action_result = {}
        final_action = Action.Accept
        for category, threshold in reject_thresholds.items():
            cate_detect_res = self.get_detect_result_by_category(category, detection_result)
            if cate_detect_res is None or "severity" not in cate_detect_res:
                raise ValueError(f"Cannot find detection result for {category}")

            severity = cate_detect_res["severity"]
            action = Action.Reject if threshold != -1 and severity >= threshold else Action.Accept
            action_result[category] = action
            if action.value > final_action.value:
                final_action = action

        return Decision(final_action, action_result)


# Flask app initialization
app = Flask(__name__)

# Configure file upload
app.config['UPLOAD_FOLDER'] = './static/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Replace with your Azure Content Safety values
endpoint = "https://sumersovitkar.cognitiveservices.azure.com/"
subscription_key = "9Q1vrNsPCUk9W4nm6F9llGpBT1QSqHEpt2Fxu0tFpNaQ7LgrnFJXJQQJ99AKACYeBjFXJ3w3AAAHACOGg97o"
api_version = "2024-09-01"

# Initialize ContentSafety object
content_safety = ContentSafety(endpoint, subscription_key, api_version)

# Function to check allowed file extensions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_image():
    if 'file' not in request.files:
        return "No file part", 400
    file = request.files['file']

    if file.filename == '':
        return "No selected file", 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Convert the image to base64
        with open(file_path, "rb") as img_file:
            img_content = base64.b64encode(img_file.read()).decode("utf-8")

        # Detect unsafe content
        detection_result = content_safety.detect(MediaType.Image, img_content)

        # Set the reject thresholds
        reject_thresholds = {
            Category.Hate: 2,
            Category.SelfHarm: 2,
            Category.Sexual: 2,
            Category.Violence: 2,
        }

        # Make decision based on detection result
        decision_result = content_safety.make_decision(detection_result, reject_thresholds)

        # Return the result
        return jsonify({
            'suggested_action': decision_result.suggested_action.name,
            'action_by_category': {category.name: action.name for category, action in decision_result.action_by_category.items()}
        })

    return "Invalid file format", 400


if __name__ == '__main__':
    app.run(debug=True)
