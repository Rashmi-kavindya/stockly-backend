# Stockly Backend

Backend API for the Stockly smart inventory management system.

## Features
- JWT authentication with role-based access control
- User, inventory, sales, goals, events, and profile APIs
- Near-expiry and dead-stock detection
- Bundle suggestion support
- Weather integration for stock suggestions
- Chatbot support with rule-based responses and AI fallback
- PDF report generation
- ML-based sales and reorder prediction

## Tech Stack
- Flask
- MySQL
- JWT
- XGBoost
- pandas
- numpy
- reportlab
- requests
- bcrypt
- joblib
- python-dotenv

## Setup
1. Create and activate a Python virtual environment.
2. Install the required dependencies.
3. Configure the MySQL database connection in your local environment.
4. Add the required environment variables in `.env` if needed.
5. Run the Flask server.

## Important Environment Variables
- `GROQ_API_KEY` for AI fallback in chat
- `GROQ_MODEL` optional, if you want to change the model name

## Main API Endpoints
- `/`
- `/login`
- `/register`
- `/users`
- `/upload_profile_pic`
- `/uploads/profile/<filename>`
- `/events`
- `/events/<int:id>`
- `/next_item_code`
- `/add_item`
- `/add_inventory`
- `/inventory`
- `/items`
- `/add_sale`
- `/bulk_sales_upload`
- `/inventory_sales/<int:item_id>`
- `/predict_sales/<int:item_id>`
- `/predict_reorder`
- `/near_expiry`
- `/dead_stock`
- `/weather`
- `/goals`
- `/goals/<int:goal_id>`
- `/goals/<int:goal_id>/progress`
- `/chat`
- `/generate_report`
- `/api/festivals`
- `/api/festivals/upcoming`

## Notes
- Make sure the frontend points to the correct backend URL.

## Author
Rashmi Kavindya
