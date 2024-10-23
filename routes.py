from flask import request, jsonify
from chatbot import Chatbot
import json

chatbot = Chatbot()

def register_routes(app):
    @app.route('/api/test')
    def test_endpoint():
        print("TEST ENDPOINT ACCESSED")
        response = {"message": "Hello from the test endpoint"}
        print(f"TEST RESPONSE: {json.dumps(response, indent=2)}")
        return response

    @app.route('/api/chat', methods=['POST'])
    def chat():
        print("\n--- NEW CHAT REQUEST ---")
        data = request.json
        print(f"REQUEST DATA: {json.dumps(data, indent=2)}")
        
        user_input = data.get('message')
        response_mode = data.get('response_mode', 'intermediate')

        if not user_input:
            error_response = {"error": "No message provided"}
            print(f"ERROR RESPONSE: {json.dumps(error_response, indent=2)}")
            return jsonify(error_response), 400

        response = chatbot.generate_response(user_input, response_mode)
        print(f"CHATBOT RESPONSE: {json.dumps(response, indent=2)}")
        
        return jsonify(response)

    @app.route('/api/feedback', methods=['POST'])
    def add_feedback():
        print("\n--- NEW FEEDBACK REQUEST ---")
        data = request.json
        print(f"FEEDBACK DATA: {json.dumps(data, indent=2)}")
        
        feedback = data.get('feedback')
        if feedback:
            chatbot.add_feedback(feedback)
            response = {"message": "Feedback added successfully"}
            print(f"FEEDBACK RESPONSE: {json.dumps(response, indent=2)}")
            return jsonify(response), 200
        
        error_response = {"error": "No feedback provided"}
        print(f"FEEDBACK ERROR: {json.dumps(error_response, indent=2)}")
        return jsonify(error_response), 400

    @app.route('/api/clear_history', methods=['POST'])
    def clear_history():
        print("\n--- CLEAR HISTORY REQUEST ---")
        chatbot.clear_history()
        response = {"message": "Chat history cleared successfully"}
        print(f"CLEAR HISTORY RESPONSE: {json.dumps(response, indent=2)}")
        return jsonify(response), 200

    @app.route('/api/clear_feedback', methods=['POST'])
    def clear_feedback():
        print("\n--- CLEAR FEEDBACK REQUEST ---")
        chatbot.clear_feedback()
        response = {"message": "Feedback cleared successfully"}
        print(f"CLEAR FEEDBACK RESPONSE: {json.dumps(response, indent=2)}")
        return jsonify(response), 200