# billing/database_integrations.py
import logging
from typing import Dict, List, Optional, Any
from decimal import Decimal
from django.utils import timezone as tz
import psycopg2
import mysql.connector
from sqlalchemy import create_engine, text, inspect
import pandas as pd
from io import StringIO

logger = logging.getLogger(__name__)

class DatabaseConnection:
    """Base class for database connections"""
    
    def __init__(self, host: str, port: int, database: str, 
                 username: str, password: str, db_type: str = 'postgresql'):
        self.host = host
        self.port = port
        self.database = database
        self.username = username
        self.password = password
        self.db_type = db_type
        self.connection = None
        self.engine = None
        
    def connect(self) -> bool:
        """Establish database connection"""
        try:
            if self.db_type == 'postgresql':
                self.connection = psycopg2.connect(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.username,
                    password=self.password,
                    connect_timeout=10
                )
                self.engine = create_engine(
                    f'postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
                )
                
            elif self.db_type == 'mysql':
                self.connection = mysql.connector.connect(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.username,
                    password=self.password,
                    connection_timeout=10
                )
                self.engine = create_engine(
                    f'mysql+mysqlconnector://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
                )
                
            elif self.db_type == 'sqlserver':
                import pyodbc
                self.connection = pyodbc.connect(
                    f'DRIVER={{ODBC Driver 17 for SQL Server}};'
                    f'SERVER={self.host},{self.port};'
                    f'DATABASE={self.database};'
                    f'UID={self.username};'
                    f'PWD={self.password};'
                )
                self.engine = create_engine(
                    f'mssql+pyodbc://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}?driver=ODBC+Driver+17+for+SQL+Server'
                )
            
            # Test connection
            if self.connection:
                cursor = self.connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                logger.info(f"Connected to {self.db_type} database at {self.host}")
                return True
                
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            self.connection = None
            self.engine = None
            
        return False
    
    def disconnect(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()
            self.connection = None
        if self.engine:
            self.engine.dispose()
            self.engine = None
    
    def execute_query(self, query: str, params: tuple = None) -> List[Dict]:
        """Execute SQL query and return results"""
        if not self.connection:
            if not self.connect():
                raise Exception("Database connection not established")
        
        try:
            cursor = self.connection.cursor()
            cursor.execute(query, params or ())
            
            if cursor.description:  # Has results
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()
                cursor.close()
                
                return [dict(zip(columns, row)) for row in rows]
            else:
                cursor.close()
                self.connection.commit()
                return []
                
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            self.connection.rollback()
            raise
    
    def get_table_info(self, table_name: str) -> Dict:
        """Get table schema information"""
        if not self.engine:
            if not self.connect():
                raise Exception("Database connection not established")
        
        inspector = inspect(self.engine)
        columns = inspector.get_columns(table_name)
        
        return {
            'table_name': table_name,
            'columns': [
                {
                    'name': col['name'],
                    'type': str(col['type']),
                    'nullable': col.get('nullable', True)
                }
                for col in columns
            ]
        }

class ISPDatabaseManager:
    """Manager for ISP database integrations"""
    
    def __init__(self, db_config: Dict):
        self.db_config = db_config
        self.db = DatabaseConnection(
            host=db_config.get('host'),
            port=db_config.get('port', 5432),
            database=db_config.get('database'),
            username=db_config.get('username'),
            password=db_config.get('password'),
            db_type=db_config.get('db_type', 'postgresql')
        )
    
    def get_data_balance_from_billing(self) -> Decimal:
        """Get available data balance from ISP billing system"""
        try:
            # Common billing system table structures
            queries = [
                # Query 1: Direct balance table
                """
                SELECT SUM(available_balance_gb) as total_balance 
                FROM data_balances 
                WHERE status = 'active' AND expiry_date > NOW()
                """,
                
                # Query 2: From customer accounts
                """
                SELECT SUM(data_balance) as total_balance
                FROM customer_accounts 
                WHERE account_status = 'active' AND data_balance > 0
                """,
                
                # Query 3: From inventory
                """
                SELECT SUM(quantity * data_per_unit_gb) as total_balance
                FROM data_inventory 
                WHERE status = 'available' AND reserved = false
                """
            ]
            
            for query in queries:
                try:
                    results = self.db.execute_query(query)
                    if results and results[0]['total_balance']:
                        return Decimal(str(results[0]['total_balance']))
                except:
                    continue
            
            return Decimal('0')
            
        except Exception as e:
            logger.error(f"Failed to get data balance: {e}")
            raise
    
    def get_customer_data_usage(self, days: int = 30) -> List[Dict]:
        """Get customer data usage statistics"""
        try:
            query = """
            SELECT 
                customer_id,
                customer_name,
                SUM(data_used_gb) as total_used_gb,
                AVG(data_used_gb) as avg_daily_usage_gb,
                COUNT(*) as usage_days
            FROM customer_usage
            WHERE usage_date >= NOW() - INTERVAL '%s DAYS'
            GROUP BY customer_id, customer_name
            ORDER BY total_used_gb DESC
            """
            
            results = self.db.execute_query(query, (days,))
            return results
            
        except Exception as e:
            logger.error(f"Failed to get customer usage: {e}")
            return []
    
    def sync_customers_to_platform(self) -> List[Dict]:
        """Sync customers from ISP database to platform"""
        try:
            query = """
            SELECT 
                id as external_id,
                name,
                email,
                phone,
                address,
                account_number,
                registration_date,
                data_balance_gb,
                account_status
            FROM customers
            WHERE account_status IN ('active', 'suspended')
            ORDER BY registration_date DESC
            LIMIT 1000
            """
            
            customers = self.db.execute_query(query)
            
            synced_customers = []
            for cust in customers:
                # Map to platform customer model
                customer_data = {
                    'external_id': cust['external_id'],
                    'name': cust['name'],
                    'email': cust['email'],
                    'phone': cust['phone'],
                    'address': cust['address'],
                    'account_number': cust['account_number'],
                    'data_balance': Decimal(str(cust.get('data_balance_gb', 0))),
                    'status': 'active' if cust['account_status'] == 'active' else 'inactive'
                }
                synced_customers.append(customer_data)
            
            return synced_customers
            
        except Exception as e:
            logger.error(f"Failed to sync customers: {e}")
            return []
    
    def import_data_transactions(self, date_from: str, date_to: str) -> List[Dict]:
        """Import data transactions from ISP system"""
        try:
            query = """
            SELECT 
                transaction_id,
                transaction_date,
                customer_id,
                customer_name,
                transaction_type,
                amount_gb,
                reference_number,
                description
            FROM data_transactions
            WHERE transaction_date BETWEEN %s AND %s
            AND transaction_type IN ('purchase', 'allocation', 'adjustment')
            ORDER BY transaction_date DESC
            """
            
            transactions = self.db.execute_query(query, (date_from, date_to))
            
            imported_transactions = []
            for tx in transactions:
                transaction_data = {
                    'external_id': tx['transaction_id'],
                    'date': tx['transaction_date'],
                    'customer_id': tx['customer_id'],
                    'customer_name': tx['customer_name'],
                    'type': tx['transaction_type'],
                    'amount_gb': Decimal(str(tx['amount_gb'])),
                    'reference': tx['reference_number'],
                    'description': tx['description']
                }
                imported_transactions.append(transaction_data)
            
            return imported_transactions
            
        except Exception as e:
            logger.error(f"Failed to import transactions: {e}")
            return []
    
    def export_to_csv(self, query: str, filename: str) -> str:
        """Export query results to CSV string"""
        try:
            if not self.db.engine:
                self.db.connect()
            
            # Use pandas to export to CSV
            df = pd.read_sql_query(text(query), self.db.engine)
            
            # Convert to CSV string
            csv_string = df.to_csv(index=False)
            return csv_string
            
        except Exception as e:
            logger.error(f"Failed to export to CSV: {e}")
            raise
    
    def test_connection(self) -> Dict:
        """Test database connection and get basic info"""
        try:
            if not self.db.connect():
                return {'success': False, 'error': 'Connection failed'}
            
            # Get database version
            version_query = "SELECT version()" if self.db_config['db_type'] == 'postgresql' else "SELECT @@version"
            version_result = self.db.execute_query(version_query)
            
            # Get tables count
            if self.db_config['db_type'] == 'postgresql':
                tables_query = """
                SELECT COUNT(*) as table_count 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                """
            elif self.db_config['db_type'] == 'mysql':
                tables_query = """
                SELECT COUNT(*) as table_count 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE()
                """
            else:
                tables_query = "SELECT 0 as table_count"
            
            tables_result = self.db.execute_query(tables_query)
            
            return {
                'success': True,
                'version': version_result[0]['version'] if version_result else 'Unknown',
                'table_count': tables_result[0]['table_count'] if tables_result else 0,
                'database': self.db_config['database'],
                'host': self.db_config['host']
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

