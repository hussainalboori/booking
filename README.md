# AI-Powered Booking & Customer Service Automation System

A lightweight, operational backend built using Python 3, Flask, and OpenAI (with robust fallback heuristics if no API key is present) to classify, route, and automatically handle customer service and booking queries.

It features a premium dark-mode web dashboard allowing users to submit requests, view AI processing results, inspect active slots and bookings, and trigger manual staff approvals.

## File Structure
- `db.py`: In-memory database storing appointment slots, staff availability, VIP list, knowledge base, and booking/request logs.
- `ai_service.py`: Service wrapper around the OpenAI client with structured classification and QA prompts, plus regex fallbacks.
- `request_handlers.py`: Business logic routing for the 5 target scenarios.
- `app.py`: Flask API exposing endpoints for request submission, dashboard status, and staff manual approvals.
- `test_scenarios.py`: Orchestrates mock traffic to cover and verify all 5 test scenarios.
- `static/index.html`: Premium single-page web dashboard interface.

## Setup & Local Execution

### Prerequisites
- Python 3.14 (or Python 3.8+)
- Active internet connection (if running with OpenAI, otherwise optional)

### Installation
1. Navigate to the project root:
   ```bash
   cd /Users/hussainalboori/Documents/booking-system
   ```
2. Create and activate a virtual environment:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_actual_openai_api_key
PORT=5000
```
*Note: If no `OPENAI_API_KEY` is supplied, the system automatically uses its rule-based heuristic classifier, allowing tests to run and pass fully without API credentials.*

### Running the API Server
Start the server locally:
```bash
python3 app.py
```
Open `http://127.0.0.1:5000` in your web browser to open the dashboard!

### Running Automated Test Scenarios
Run the full simulation covering the 5 customer scenarios and the staff manual approval endpoint:
```bash
python3 test_scenarios.py
```
