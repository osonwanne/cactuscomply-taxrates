# cactuscomply-taxrates
Arizona TPT tax rates

# Tax Rates Intake Application

A Flask web application for uploading and processing Arizona TPT (Transaction Privilege Tax) rates from CSV files.

## Features

- **CSV Upload Interface**: Drag-and-drop or click-to-upload CSV files
- **Data Validation**: Validates CSV format and data integrity
- **Database Storage**: Stores tax rates in PostgreSQL with proper relationships
- **Upload History**: Tracks all uploads with error reporting
- **Rate Viewing**: View and filter uploaded tax rates
- **API Endpoints**: REST API for accessing rate data

## Database Schema

### Reference Tables

- `ref_business_class`: Business classification codes (e.g., '017' = Retail)
- `ref_region`: Region codes (counties, cities, districts)
- `ref_deduction_code`: Deduction codes for future use

### Main Tables

- `tpt_rates`: Monthly tax rates by business class and region
- `upload_log`: Upload history and error tracking

## Installation

1. **Clone and setup**:

   ```bash
   cd tax-rates-intake
   pip install -r requirements.txt
   ```

2. **Database Setup**:

   ```bash
   # Set your database URL
   export DATABASE_URL="postgresql://username:password@localhost/tax_rates_db"

   # Run the application (it will create tables automatically)
   python app.py
   ```

3. **Access the application**:
   - Open http://localhost:5000 in your browser
   - Upload CSV files from Arizona Department of Revenue

## CSV Format

The application expects CSV files with these columns:

- `Business Class Code`: e.g., '017', '011'
- `Region Code`: e.g., 'PMA', 'PH'
- `State Rate`: Decimal rate (e.g., 0.0560)
- `County Rate`: Decimal rate (e.g., 0.0075)
- `City Rate`: Decimal rate (e.g., 0.0200)

## Usage

1. **Upload CSV**: Use the main upload page to upload ADOR CSV files
2. **View Rates**: Browse uploaded rates with filtering options
3. **Check History**: Review upload history and any errors
4. **API Access**: Use `/api/rates/<date>` to get rates by effective date

## Environment Variables

- `DATABASE_URL`: PostgreSQL connection string
- `SECRET_KEY`: Flask secret key for sessions

## Production Deployment

For production deployment:

1. **Use Gunicorn**:

   ```bash
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

2. **Set environment variables**:

   ```bash
   export DATABASE_URL="your_production_db_url"
   export SECRET_KEY="your_secret_key"
   ```

3. **Configure reverse proxy** (nginx/Apache) for static files and SSL

## API Endpoints

- `GET /api/rates/<effective_date>`: Get rates for specific date
- `POST /upload`: Upload CSV file
- `GET /rates`: View rates page
- `GET /uploads`: View upload history

## Error Handling

The application provides comprehensive error handling:

- CSV format validation
- Database constraint checking
- Upload progress tracking
- Detailed error reporting in upload history

## Data Sources

This application is designed to work with data from:

- Arizona Department of Revenue TPT Rate Tables
- Monthly CSV files published by ADOR
- Business Class Codes and Region Codes from ADOR documentation
