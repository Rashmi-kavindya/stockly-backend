"""
Chat Rules & Natural Language Query Handler for Stockly

This module handles natural language queries from users and converts them
into SQL queries using the database schema rules defined in the database.

Rules:
- Detect user intent from keywords
- Map intent to appropriate SQL query
- Execute query and format response
- Handle edge cases gracefully
- Support NLP preprocessing for better accuracy
"""

import mysql.connector
from datetime import datetime, timedelta
import re
import string


class ChatRulesEngine:
    """Process natural language queries and execute relevant SQL."""
    
    def __init__(self, db_connection_func):
        """
        Args:
            db_connection_func: Function that returns a DB connection
        """
        self.get_db_connection = db_connection_func
    
    # ====================================================================
    # NLP PREPROCESSING
    # ====================================================================
    
    def preprocess_query(self, query):
        """
        Preprocess input query for better NLP analysis.
        - Remove extra whitespace
        - Convert to lowercase
        - Remove punctuation
        - Tokenize
        """
        if not query:
            return []
        
        # Remove extra whitespace
        query = ' '.join(query.split())
        
        # Convert to lowercase
        query_lower = query.lower()
        
        # Remove punctuation except for contractions
        query_clean = query_lower.translate(str.maketrans('', '', string.punctuation))
        
        # Tokenize (split into words)
        tokens = query_clean.split()
        
        return tokens
    
    def check_greeting(self, query):
        """Check if query is a greeting."""
        greetings = ['hello', 'hi', 'hey', 'greetings', 'howdy', 'good morning', 
                    'good afternoon', 'good evening', 'whats up', 'what\'s up']
        query_lower = query.lower()
        
        for greeting in greetings:
            if greeting in query_lower:
                responses = [
                    "👋 Hello! Welcome to Stockly. How can I help you today?",
                    "👋 Hi there! I'm here to help with sales, stock, expiry alerts, and more. What do you need?",
                    "👋 Hey! Ask me about inventory, sales, goals, or dead stock analysis."
                ]
                return responses[hash(query) % len(responses)]
        
        return None
    
    def check_gratitude(self, query):
        """Check if query contains gratitude."""
        gratitude_words = ['thank', 'thanks', 'appreciate', 'grateful', 'thank you',
                          'thankyou', 'much appreciated', 'awesome', 'great job']
        query_lower = query.lower()
        
        for word in gratitude_words:
            if word in query_lower:
                responses = [
                    "😊 You're welcome! Happy to help. Anything else?",
                    "😊 Always happy to assist! Need more info?",
                    "😊 Glad I could help! Let me know if you need anything else."
                ]
                return responses[hash(query) % len(responses)]
        
        return None
    
    def check_help_request(self, query):
        """Check if user is requesting help."""
        help_words = ['help', 'assist', 'support', 'how do i', 'how can i', 
                     'what can', 'guide', 'tutorial', 'feature']
        query_lower = query.lower()
        
        for word in help_words:
            if word in query_lower:
                help_text = """
📚 **Stockly Chat Assistant - Help Guide**

I can help you with:

**📊 Sales Analytics**
- "Show sales for Coca Cola"
- "What were last month's sales?"
- "Top selling products?"

**📦 Inventory Management**
- "How much stock for pencil?"
- "Show available inventory"
- "Low stock items?"

**⏰ Expiry Management**
- "Items expiring soon?"
- "Expiry alerts for next 30 days"
- "Expired products?"

**🎯 Goal Tracking**
- "Show my sales goals"
- "Goal progress?"
- "Upcoming deadlines?"

**📉 Dead Stock Analysis**
- "Slow moving items?"
- "Dead stock report"
- "Items with no sales?"

**👤 Support**
- Admin Contact: admin@stockly.local
- Email: support@stockly.com

Just ask naturally! 😊
                """
                return help_text
        
        return None
    
    # ====================================================================
    # INTENT DETECTION
    # ====================================================================
    
    def detect_intent(self, query):
        """Detect user intent from keywords."""
        query_lower = query.lower().strip()
        # Report generation intent
        if any(word in query_lower for word in ['report', 'report generation', 'generate report']):
            return 'report'
        
        # Sales intent
        if any(word in query_lower for word in ['sales', 'sold', 'revenue', 'sell', 
                                                   'how much', 'earnings', 'income', 'profit']):
            return 'sales'
        
        # Stock/Inventory intent
        if any(word in query_lower for word in ['stock', 'inventory', 'available', 'quantity', 
                                                   'how many', 'count', 'amount', 'units']):
            return 'stock'
        
        # Expiry/Near-expiry intent
        if any(word in query_lower for word in ['expiry', 'expire', 'expired', 'expiring', 
                                                   'expire soon', 'shelf life', 'best before']):
            return 'expiry'
        
        # Goal/Target intent
        if any(word in query_lower for word in ['goal', 'target', 'progress', 'achieved', 
                                                   'objective', 'deadline', 'milestone']):
            return 'goals'
        
        # Prediction/Forecast intent
        if any(word in query_lower for word in ['predict', 'forecast', 'reorder', 'need', 
                                                   'suggest', 'recommend', 'estimate']):
            return 'predict'
        
        # Dead stock intent
        if any(word in query_lower for word in ['dead stock', 'slow moving', 'slowmoving', 
                                                   'no sales', 'stagnant', 'inactive']):
            return 'dead_stock'
        
        return 'general'
    
    # ====================================================================
    # PRODUCT LOOKUP
    # ====================================================================
    
    def find_item_by_name(self, query):
        """Extract item name from query and find matching item_id."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            
            # Common item aliases and mappings
            common_items = {
                'a4': 'A4 Sheet Ream 500pcs',
                'glue': 'Glue Stick 20g',
                'pencil': 'Pencil HB',
                'notebook': 'Spiral Notebook A4 100p',
                'pen': 'Ballpoint Pen Blue',
                'chicken': 'Frozen Chicken 1kg',
                'fries': 'Frozen Fries 1kg',
                'coca cola': 'Coca Cola 1L',
                'coke': 'Coca Cola 1L',
                'sprite': 'Sprite 1L',
                'tea': 'Ceylon Tea 250g',
                'soap': 'Lifebuoy Soap 100g',
                'shampoo': 'Shampoo 400ml',
                'toothpaste': 'Toothpaste 120g',
                'ice cream': 'Ice Cream 1L',
                'noodles': 'Noodles 400g',
                'sugar': 'Sugar 1kg',
                'flour': 'Wheat Flour 1kg',
                'coffee': 'Nescafe 100g',
                'milo': 'Milo Packet 200g',
                'milk': 'Anchor Milk Powder 400g',
                'tissue': 'Tissue Roll 2ply 4pcs',
                'garbage bag': 'Garbage Bag Large 10pcs',
                'dish wash': 'Dish Wash Liquid 500ml',
                'handwash': 'Handwash 200ml',
                'hand sanitizer': 'Hand Sanitizer 500ml',
            }
            
            # Check against common items first
            for key, item_name in common_items.items():
                if key in query.lower():
                    cur.execute("SELECT item_id, item_name FROM items WHERE item_name = %s", (item_name,))
                    result = cur.fetchone()
                    if result:
                        return result
        
        except Exception as e:
            # Log the error but don't crash - return None and let caller handle it
            print(f"Database error in find_item_by_name: {str(e)}")
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return None
    
    # ====================================================================
    # SALES QUERIES
    # ====================================================================
    
    def handle_sales_query(self, query, user_id=None):
        """Handle sales-related queries."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            query_lower = query.lower()
            now = datetime.now()

            # Determine target month/year
            if 'last month' in query_lower or 'previous month' in query_lower:
                if now.month == 1:
                    target_month = 12
                    target_year = now.year - 1
                else:
                    target_month = now.month - 1
                    target_year = now.year
                label = 'Last month'
            else:
                # Default to current month
                target_month = now.month
                target_year = now.year
                label = 'This month'

            item = self.find_item_by_name(query)

            # Specific item sales (current/last month only)
            if item:
                cur.execute("""
                    SELECT i.item_name, COALESCE(SUM(sh.quantity_sold), 0) as total
                    FROM sales_history sh
                    JOIN items i ON sh.item_id = i.item_id
                    WHERE sh.item_id = %s AND sh.month = %s AND sh.year = %s
                    GROUP BY i.item_name
                """, (item['item_id'], target_month, target_year))
                row = cur.fetchone()
                total = row['total'] if row else 0
                if total > 0:
                    response = (
                        f"Sales for {item['item_name']} - {label}: "
                        f"{total} units ({target_month}/{target_year})"
                    )
                else:
                    response = f"No sales data for {item['item_name']} in {target_month}/{target_year}."

            # Top selling items for target month
            else:
                cur.execute("""
                    SELECT i.item_name, SUM(sh.quantity_sold) as total
                    FROM sales_history sh
                    JOIN items i ON sh.item_id = i.item_id
                    WHERE sh.month = %s AND sh.year = %s
                    GROUP BY sh.item_id
                    ORDER BY total DESC
                    LIMIT 10
                """, (target_month, target_year))
                rows = cur.fetchall()
                if rows:
                    response = (
                        f"{label} top sales (Top 10):\n" + "\n".join(
                            [f"  - {i+1}. {r['item_name']}: {r['total']} units" for i, r in enumerate(rows)]
                        )
                    )
                else:
                    response = f"No sales data for {target_month}/{target_year}."
        
        except Exception as e:
            response = f"Error retrieving sales data: {str(e)}"
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return response
    
    # ====================================================================
    # STOCK QUERIES
    # ====================================================================
    
    def handle_stock_query(self, query, user_id=None):
        """Handle inventory/stock queries."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            item = self.find_item_by_name(query)
            if item:
                cur.execute("""
                    SELECT COALESCE(SUM(ib.stock_quantity), 0) as stock, i.reorder_level
                    FROM items i
                    LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
                    WHERE i.item_id = %s
                    AND (ib.expire_date > CURDATE() OR ib.id IS NULL)
                    GROUP BY i.item_id
                """, (item['item_id'],))
                row = cur.fetchone()
                stock = row['stock'] if row else 0
                reorder = row['reorder_level'] if row else 10
                
                if stock < reorder:
                    status = "⚠️ **LOW STOCK**"
                elif stock < reorder * 2:
                    status = "🟡 **MODERATE**"
                else:
                    status = "✅ **ADEQUATE**"
                
                response = f"{status} - **{item['item_name']}**\n  Stock: **{stock} units**\n  Reorder Level: **{reorder} units**"
            
            else:
                cur.execute("""
                    SELECT i.item_name, COALESCE(SUM(ib.stock_quantity), 0) as stock, i.reorder_level
                    FROM items i
                    LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
                    WHERE ib.expire_date > CURDATE() OR ib.id IS NULL
                    GROUP BY i.item_id
                    ORDER BY stock DESC
                    LIMIT 10
                """)
                rows = cur.fetchall()
                if rows:
                    response = "📦 **Top 10 stocked items:**\n" + "\n".join(
                        [f"  • {r['item_name']}: **{r['stock']} units**" for r in rows]
                    )
                else:
                    response = "❌ No inventory data available."
        
        except Exception as e:
            response = f"❌ Error retrieving stock data: {str(e)}"
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return response
    
    # ====================================================================
    # EXPIRY QUERIES
    # ====================================================================
    
    def handle_expiry_query(self, query, days=30, user_id=None):
        """Handle expiry/near-expiry queries."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            # Extract days if mentioned
            if 'soon' in query.lower() or '7' in query:
                days = 7
            elif '14' in query:
                days = 14
            elif '60' in query:
                days = 60
            
            # Fixed: GROUP BY must include all non-aggregated columns to comply with ONLY_FULL_GROUP_BY
            cur.execute("""
                SELECT i.item_name, ib.expire_date, SUM(ib.stock_quantity) as stock
                FROM inventory_batches ib
                JOIN items i ON ib.item_id = i.item_id
                WHERE ib.expire_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL %s DAY)
                AND ib.stock_quantity > 0
                GROUP BY i.item_id, i.item_name, ib.expire_date
                ORDER BY ib.expire_date ASC
            """, (days,))
            rows = cur.fetchall()
            
            if rows:
                response = f"⏰ **Items expiring in {days} days:** ({len(rows)} items)\n" + "\n".join(
                    [f"  • {r['item_name']}: Expires **{r['expire_date'].strftime('%Y-%m-%d')}** ({r['stock']} units)" 
                     for r in rows]
                )
            else:
                response = f"✅ **Good news!** No items expiring in the next {days} days."
        
        except Exception as e:
            response = f"❌ Error retrieving expiry data: {str(e)}"
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return response
    
    # ====================================================================
    # GOAL QUERIES
    # ====================================================================
    
    def handle_goals_query(self, query, user_id=None):
        """Handle goal/target queries."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            if not user_id:
                response = "❌ Please log in to view your goals."
            else:
                cur.execute("""
                    SELECT g.title, i.item_name, g.target, g.deadline, g.status,
                           COALESCE(SUM(st.quantity_sold), 0) as current,
                           CASE 
                               WHEN g.target > 0 THEN ROUND((COALESCE(SUM(st.quantity_sold), 0) / g.target) * 100, 1)
                               ELSE 0
                           END as progress
                    FROM goals g
                    LEFT JOIN items i ON g.item_id = i.item_id
                    LEFT JOIN sales_history st ON g.item_id = st.item_id 
                    WHERE g.user_id = %s
                    GROUP BY g.id
                    ORDER BY g.deadline ASC
                """, (user_id,))
                rows = cur.fetchall()
                
                if rows:
                    response = "🎯 **Your sales goals:**\n" + "\n".join([
                        f"  • **{r['title']}** ({r['item_name']})\n    Progress: **{r['current']}/{r['target']}** units (**{r['progress']}%**) - Due **{r['deadline'].strftime('%Y-%m-%d')}** [{r['status'].upper()}]"
                        for r in rows
                    ])
                else:
                    response = "📭 You have no active goals yet. Set a goal to track your sales targets!"
        
        except Exception as e:
            response = f"❌ Error retrieving goals: {str(e)}"
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return response
    
    # ====================================================================
    # DEAD STOCK QUERIES
    # ====================================================================
    
    def handle_dead_stock_query(self, query, user_id=None):
        """Handle dead stock (slow-moving items) queries."""
        conn = None
        cur = None
        
        try:
            conn = self.get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("""
                SELECT i.item_name, COALESCE(SUM(ib.stock_quantity), 0) as stock,
                       COALESCE(SUM(sh.quantity_sold), 0) as total_sales
                FROM items i
                LEFT JOIN inventory_batches ib ON i.item_id = ib.item_id
                LEFT JOIN sales_history sh ON i.item_id = sh.item_id
                WHERE ib.expire_date > CURDATE() OR ib.id IS NULL
                GROUP BY i.item_id
                HAVING total_sales < 50 OR total_sales IS NULL
                ORDER BY total_sales ASC
                LIMIT 10
            """)
            rows = cur.fetchall()
            
            if rows:
                response = "📉 **Dead stock alert (low-selling items - Top 10):**\n" + "\n".join([
                    f"  • {r['item_name']}: **{r['stock']} units** in stock, **{r['total_sales']} total sales**"
                    for r in rows
                ])
            else:
                response = "✅ **Excellent!** No dead stock detected. All items are moving well."
        
        except Exception as e:
            response = f"❌ Error retrieving dead stock data: {str(e)}"
        
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
        
        return response

    # ====================================================================
    # REPORT PROMPT
    # ====================================================================

    def handle_report_query(self, query, user_id=None):
        """Return a structured prompt describing available report types and months.

        This returns a dict so the frontend can render a form/buttons.
        """
        months = [
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December', 'All'
        ]

        payload = {
            'type': 'report_prompt',
            'title': 'Which report do you need?',
            'options': ['sales', 'inventory'],
            'months': months
        }

        return payload
    
    # ====================================================================
    # GENERAL QUERIES (UNSUPPORTED/OTHER)
    # ====================================================================
    
    def handle_general_query(self, query):
        """Handle general queries not related to database."""
        # Return None to signal "no rule/db match" so caller can fall back to AI.
        return None
    
    # ====================================================================
    # MAIN HANDLER
    # ====================================================================
    
    def process_query(self, query, user_id=None):
        """
        Main entry point: Process natural language query intelligently.
        
        Args:
            query (str): User's natural language query
            user_id (int): Optional user ID for personalized responses
        
        Returns:
            str: Formatted response ready for API return
        """
        if not query or not query.strip():
            return "❓ Please ask me something! Type 'help' for options."
        
        # Check for greetings first
        greeting_response = self.check_greeting(query)
        if greeting_response:
            return greeting_response
        
        # Check for gratitude
        gratitude_response = self.check_gratitude(query)
        if gratitude_response:
            return gratitude_response
        
        # Check for help request
        help_response = self.check_help_request(query)
        if help_response:
            return help_response
        
        # Preprocess query for better analysis
        tokens = self.preprocess_query(query)
        
        # Detect intent
        intent = self.detect_intent(query)
        
        # Route to appropriate handler
        if intent == 'report':
            return self.handle_report_query(query, user_id)
        if intent == 'sales':
            return self.handle_sales_query(query, user_id)
        elif intent == 'stock':
            return self.handle_stock_query(query, user_id)
        elif intent == 'expiry':
            return self.handle_expiry_query(query, user_id=user_id)
        elif intent == 'goals':
            return self.handle_goals_query(query, user_id)
        elif intent == 'dead_stock':
            return self.handle_dead_stock_query(query, user_id)
        else:
            return self.handle_general_query(query)
