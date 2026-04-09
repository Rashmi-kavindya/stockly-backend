# Stockly Backend

Backend API for the Stockly smart inventory management system.

## Features
- JWT authentication and role-based access control
- Inventory, sales, users, goals, events, and alerts APIs
- Near-expiry and dead-stock detection
- Bundle suggestion support
- Weather data integration
- Chatbot and report-generation endpoints
- ML-based sales/reorder prediction

## Tech Stack
- Flask
- MySQL
- XGBoost
- JWT
- Python libraries used in the project

## Setup
1. Create and activate a virtual environment
2. Install dependencies
3. Configure your database connection
4. Run the Flask server

## API Overview
- `/login`
- `/register`
- `/items`
- `/inventory`
- `/add_sale`
- `/near_expiry`
- `/dead_stock`
- `/goals`
- `/events`
- `/weather`
- `/chat`
- `/generate_report`

## Notes
- Make sure the frontend points to the correct backend URL.
  
## Author
Rashmi Kavindya
