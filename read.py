# product_data_manager.py
# This file contains the ProductDataManager class for all data-related operations.

import pandas as pd


class ProductDataManager:
    """
    Handles loading, saving, and querying product and stock data from CSV files.
    """

    def __init__(self, products_filepath, stock_filepath):
        """
        Initialize the ProductDataManager with file paths.

        Parameters:
        products_filepath (str): Path to the products CSV file.
        stock_filepath (str): Path to the stock CSV file.
        """
        self.products_filepath = products_filepath
        self.stock_filepath = stock_filepath
        self.products_df = pd.DataFrame()
        self.stock_df = pd.DataFrame()

    # ----------------------------
    # File Operations
    # ----------------------------

    def load_data(self, file_path, columns=None):
        """
        Load data from a CSV file.

        Parameters:
        file_path (str): Path to the CSV file.
        columns (list or None): Optional list of column names to load.

        Returns:
        pd.DataFrame: The loaded DataFrame, or empty DataFrame on error.
        """
        try:
            # Check if the file is a valid CSV
            if not file_path.lower().endswith('.csv'):
                raise ValueError("Invalid file type. Please select a CSV file.")
            
            df = pd.read_csv(file_path, usecols=columns)
            return df
        except Exception as e:
            print(f"[ERROR] Could not load {file_path}: {e}")
            return pd.DataFrame()

    def save_data(self, data, file_path):
        """
        Save a DataFrame to a CSV file.

        Parameters:
        data (pd.DataFrame): DataFrame to save.
        file_path (str): File path to save to.
        """
        try:
            data.to_csv(file_path, index=False)
        except Exception as e:
            print(f"[ERROR] Could not write to {file_path}: {e}")

    def load_all(self):
        """
        Load both the products and stock CSV files into memory.
        """
        self.products_df = self.load_data(self.products_filepath)
        self.stock_df = self.load_data(self.stock_filepath)

    def save_all(self):
        """
        Save both the products and stock DataFrames to their files.
        """
        self.save_data(self.products_df, self.products_filepath)
        self.save_data(self.stock_df, self.stock_filepath)
    
    # ----------------------------
    # New loading methods for the GUI
    # ----------------------------
    def load_products_from_file(self, file_path):
        """
        Load products from a chosen CSV file.
        """
        self.products_filepath = file_path
        self.products_df = self.load_data(file_path)

    def load_stock_from_file(self, file_path):
        """
        Load stock from a chosen CSV file.
        """
        self.stock_filepath = file_path
        self.stock_df = self.load_data(file_path)

    # ----------------------------
    # Query Functions
    # ----------------------------

    def get_product_by_tag(self, rfid_tag_id):
        """
        Find a product using its RFID tag.

        Parameters:
        rfid_tag_id (str): RFID tag to search for.

        Returns:
        pd.Series or None: The product row, or None if not found.
        """
        if self.products_df.empty:
            return None

        match = self.products_df[self.products_df['rfid_tag_id'] == rfid_tag_id]
        if not match.empty:
            return match.iloc[0]
        return None

    def get_stock_by_product(self, product_name):
        """
        Find stock entries for a given product name.

        Parameters:
        product_name (str): The product name.

        Returns:
        pd.DataFrame: Stock entries for that product.
        """
        if self.stock_df.empty:
            return pd.DataFrame()

        return self.stock_df[self.stock_df['product_name'] == product_name]

    def search_products(self, keyword):
        """
        Search for products whose name contains the keyword.

        Parameters:
        keyword (str): Keyword to search for.

        Returns:
        pd.DataFrame: Matching products.
        """
        if self.products_df.empty:
            return pd.DataFrame()

        return self.products_df[
            self.products_df['product_name'].str.contains(keyword, case=False, na=False)
        ]

    def update_product_location(self, rfid_tag_id, new_location):
        """
        Update the location of a product.

        Parameters:
        rfid_tag_id (str): RFID tag of the product to update.
        new_location (str): New location value.

        Returns:
        bool: True if update was successful, False otherwise.
        """
        if self.products_df.empty:
            return False

        mask = self.products_df['rfid_tag_id'] == rfid_tag_id
        if not mask.any():
            return False

        self.products_df.loc[mask, 'current_location'] = new_location
        return True
