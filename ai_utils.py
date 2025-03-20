#!/usr/bin/env python

from dotenv import load_dotenv
import os
import json
import pymysql

def load_config():
    """
    Load Drupal database configuration from environment variables.
    Returns:
        dict: Database configuration parameters
    Raises:
        EnvironmentError: If required environment variables are missing
    """
    load_dotenv()

    required_vars = ['DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME']
    missing_vars = [var for var in required_vars if os.getenv(var) is None]

    if missing_vars:
        raise EnvironmentError(f"Missing environment variables: {', '.join(missing_vars)}")

    config = {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT")),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME")
    }

    return config

def title_exists(title):
    """
    Check if a title exists in the node_field_data table.
    Args:
        title (str): The title to search for
    Returns:
        bool: True if the title exists (count >= 1), False otherwise
    """
    try:
        # Load database configuration from file
        db_config = load_config()
        # Establish connection
        connection = pymysql.connect(**db_config)
        # Create a cursor
        with connection.cursor() as cursor:
            # Use parameterized query to prevent SQL injection
            query = "SELECT COUNT(*) FROM node_field_data WHERE title = %s"
            cursor.execute(query, (title,))
            # Fetch the count
            result = cursor.fetchone()
            count = result[0] if result else 0
        # Close connection
        connection.close()
        # Return True if count is 1 or higher, False otherwise
        return count >= 1
    except FileNotFoundError as err:
        print(f"Configuration error: {err}")
        raise
    except json.JSONDecodeError as err:
        print(f"Invalid JSON in configuration file: {err}")
        raise
    except pymysql.Error as err:
        print(f"Database error: {err}")
        return False

def get_environmental_issues():
    """
    Fetch the list of environmental issues from the Drupal taxonomy_term_field_data table.
    
    Returns:
        list: A list of environmental issue names
    """
    try:
        # Load database configuration from file
        db_config = load_config()

        # Establish connection
        connection = pymysql.connect(**db_config)
        
        # Create a cursor
        with connection.cursor() as cursor:
            # Query to fetch environmental issues
            query = "SELECT name FROM taxonomy_term_field_data WHERE vid = 'environmental_issues' ORDER BY name"
            cursor.execute(query)
            
            # Fetch all results
            results = cursor.fetchall()
            
            # Extract names from results
            issues = [row[0] for row in results]
        
        # Close connection
        connection.close()
        
        return issues
    except Exception as e:
        print(f"Error fetching environmental issues: {e}")
        # Return default list as fallback
        return [
            "Automobiles and Trucks",
            "Boats",
            "Chemicals",
            "Construction Equipment",
            "Drinking Water",
            "Hazardous Waste",
            "Oil and Gas",
            "Sewage"
        ]
