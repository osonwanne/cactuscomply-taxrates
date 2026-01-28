from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.utils import secure_filename
import os
import csv
import io
from datetime import datetime, date
from decimal import Decimal
import logging
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'uploads')
app.config['MAX_CONTENT_SIZE'] = int(os.getenv('MAX_UPLOAD_SIZE', 16 * 1024 * 1024)) # 16MB max file size

# Supabase configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def init_database():
    """Initialize database tables."""
    try:
        # Check if tables exist by trying to query them
        logger.info("Checking database connection and existing tables...")
        
        # Test connection by querying existing tables
        try:
            # Check jurisdictions table
            result = supabase.table('jurisdictions').select('id').limit(1).execute()
            logger.info("✅ jurisdictions table exists")
            
            # Check rate_versions table  
            result = supabase.table('rate_versions').select('id').limit(1).execute()
            logger.info("✅ rate_versions table exists")
            
            # Check rates table
            result = supabase.table('rates').select('id').limit(1).execute()
            logger.info("✅ rates table exists")
            
            # Check business_class_codes table
            result = supabase.table('business_class_codes').select('code').limit(1).execute()
            logger.info("✅ business_class_codes table exists")
            
            logger.info("All required tables exist - database ready!")
            return True
            
        except Exception as e:
            logger.error(f"Database connection or table check failed: {e}")
            logger.info("Please ensure the following tables exist in your Supabase database:")
            logger.info("- jurisdictions")
            logger.info("- rate_versions") 
            logger.info("- rates")
            logger.info("- business_class_codes")
            return False
            
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        return False

def upsert_business_codes(rates_data):
    """Upsert business codes from rates data using the same approach as ador_sync_service."""
    try:
        business_codes = {}
        for rate in rates_data:
            code = rate['business_code']
            name = rate['business_name']
            if code and code not in business_codes:
                business_codes[code] = name or f'Business Code {code}'
        
        processed = 0
        for code, description in business_codes.items():
            try:
                supabase.table("business_class_codes").upsert({
                    'code': code,
                    'description': description
                }).execute()
                processed += 1
            except Exception as e:
                logger.error(f"Error upserting business code {code}: {e}")
        
        logger.info(f"Processed {processed} business codes")
        return processed
        
    except Exception as e:
        logger.error(f"Error upserting business codes: {e}")
        return 0

def upsert_jurisdictions(rates_data):
    """Upsert jurisdictions from rates data using the same approach as ador_sync_service."""
    try:
        # Extract unique region codes
        jurisdictions = {}
        for rate in rates_data:
            region_code = rate['region_code']
            region_name = rate['region_name']
            if region_code and region_code not in jurisdictions:
                jurisdictions[region_code] = {
                    'code': region_code,
                    'name': region_name or f"{region_code} City"
                }
        
        # Get the current max ID from the database
        max_id_result = supabase.table("jurisdictions").select("id").order("id", desc=True).limit(1).execute()
        jurisdiction_id_counter = (max_id_result.data[0]['id'] + 1) if max_id_result.data else 1
        
        # Upsert to database (using existing jurisdictions table structure)
        processed = 0
        for region_code, jurisdiction_data in jurisdictions.items():
            try:
                # Map to existing table structure
                city_code = region_code
                
                # Check if jurisdiction already exists by city_code
                existing = supabase.table("jurisdictions").select("id").eq("city_code", city_code).execute()
                
                if existing.data:
                    # Update existing jurisdiction (don't change ID)
                    existing_id = existing.data[0]['id']
                    update_data = {
                        'level': 'city',
                        'state_code': 'AZ',
                        'county_name': None,  # Always None for city jurisdictions
                        'city_name': jurisdiction_data['name']
                    }
                    supabase.table("jurisdictions").update(update_data).eq("id", existing_id).execute()
                    logger.info(f"Updated jurisdiction {city_code} (ID: {existing_id})")
                    processed += 1
                else:
                    # Insert new jurisdiction with auto-incremented ID
                    jurisdiction_record = {
                        'id': jurisdiction_id_counter,
                        'level': 'city',
                        'state_code': 'AZ',
                        'county_name': None,  # Always None for city jurisdictions
                        'city_code': city_code,
                        'city_name': jurisdiction_data['name']
                    }
                    supabase.table("jurisdictions").insert(jurisdiction_record).execute()
                    logger.info(f"Inserted new jurisdiction {city_code} (ID: {jurisdiction_id_counter})")
                    processed += 1
                    jurisdiction_id_counter += 1
                    
            except Exception as e:
                logger.error(f"Error upserting jurisdiction {region_code}: {e}")
        
        logger.info(f"Processed {processed} jurisdictions (new + updated)")
        return processed
        
    except Exception as e:
        logger.error(f"Error upserting jurisdictions: {e}")
        return 0

def create_rate_version(effective_date, uploader):
    """Create a new rate version and return its ID."""
    try:
        result = supabase.table('rate_versions').insert({
            'effective_date': effective_date,
            'loaded_at': datetime.now().isoformat()  # Use current timestamp
        }).execute()
        
        if result.data:
            rate_version_id = result.data[0]['id']
            logger.info(f"Created rate version {rate_version_id} for date {effective_date}")
            return rate_version_id
        else:
            raise RuntimeError("Failed to create rate version")
    except Exception as e:
        logger.error(f"Error creating rate version: {e}")
        raise

def upsert_tax_rates(rates_data, rate_version_id, uploader):
    """Upsert tax rates data."""
    try:
        count = 0
        
        for rate in rates_data:
            try:
                # Get jurisdiction ID by city_code (not region_code)
                jurisdiction_result = supabase.table('jurisdictions').select('id').eq('city_code', rate['region_code']).execute()
                if not jurisdiction_result.data:
                    logger.warning(f"Jurisdiction not found for code: {rate['region_code']}")
                    continue
                
                jurisdiction_id = jurisdiction_result.data[0]['id']
                
                # Prepare rate data - insert into rates table (current_rates is a view)
                rate_data = {
                    'rate_version_id': rate_version_id,
                    'business_code': rate['business_code'],
                    'jurisdiction_id': jurisdiction_id,
                    'state_rate': rate['state_rate'],
                    'county_rate': rate['county_rate'],
                    'city_rate': rate['city_rate']
                }
                
                # Insert into rates table (current_rates is a view that will automatically show this data)
                supabase.table('rates').upsert(rate_data).execute()
                count += 1
                
            except Exception as e:
                logger.warning(f"Error upserting rate for {rate['business_code']}-{rate['region_code']}: {e}")
                continue
        
        logger.info(f"Upserted {count} tax rates")
        return count
    except Exception as e:
        logger.error(f"Error upserting tax rates: {e}")
        return 0

def parse_csv_content(csv_content: str, effective_date: str, uploader: str) -> dict:
    """
    Parse CSV content using the same structure as cactuscomply-integrations
    """
    try:
        logger.info(f"Parsing CSV content uploaded by: {uploader}")
        
        # Parse CSV content (handle BOM)
        csv_io = io.StringIO(csv_content)
        reader = csv.DictReader(csv_io)
        
        rates_data = []
        for row in reader:
            try:
                # Extract data from actual CSV format (handle BOM in field names)
                region_code = row.get('RegionCode', row.get('\ufeffRegionCode', '')).strip()
                region_name = row.get('RegionName', '').strip()
                business_code = row.get('BusinessCode', '').strip()
                business_name = row.get('BusinessCodesName', '').strip()
                tax_rate = row.get('TaxRate', '0').strip()
                
                # Parse the tax rate (convert percentage to decimal)
                try:
                    rate_value = float(tax_rate.replace('%', ''))
                    # Convert percentage to decimal (e.g., 2.4% -> 0.024)
                    if rate_value > 1:
                        rate_decimal = rate_value / 100.0
                    else:
                        rate_decimal = rate_value
                except (ValueError, AttributeError):
                    rate_decimal = 0.0
                
                if region_code and business_code and rate_decimal > 0:
                    rates_data.append({
                        'region_code': region_code,
                        'region_name': region_name,
                        'business_code': business_code,
                        'business_name': business_name,
                        'state_rate': 0.0,  # ADOR CSV doesn't separate by state/county/city
                        'county_rate': 0.0,
                        'city_rate': rate_decimal,  # Put the rate in city_rate for now
                        'total_rate': rate_decimal,
                        'effective_date': effective_date,
                        'uploader': uploader
                    })
                    
            except Exception as e:
                logger.warning(f"Error parsing row {row}: {e}")
                continue
        
        if not rates_data:
            raise RuntimeError("No valid rates data found in CSV")
        
        logger.info(f"Successfully parsed {len(rates_data)} rate records from CSV")
        
        # Process data in order
        business_codes_count = upsert_business_codes(rates_data)
        jurisdictions_count = upsert_jurisdictions(rates_data)
        rate_version_id = create_rate_version(effective_date, uploader)
        rates_count = upsert_tax_rates(rates_data, rate_version_id, uploader)
        
        return {
            'total_records': len(rates_data),
            'inserted_count': rates_count,
            'updated_count': 0,  # We're doing upserts, so this is insert count
            'business_codes_processed': business_codes_count,
            'jurisdictions_processed': jurisdictions_count,
            'errors': [],
            'success': True
        }
        
    except Exception as e:
        logger.error(f"CSV parsing error: {str(e)}")
        return {
            'total_records': 0,
            'inserted_count': 0,
            'updated_count': 0,
            'business_codes_processed': 0,
            'jurisdictions_processed': 0,
            'errors': [f"CSV parsing error: {str(e)}"],
            'success': False
        }

@app.route('/')
def index():
    """Main upload page."""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and processing."""
    if 'file' not in request.files:
        flash('No file selected', 'error')
        return redirect(request.url)
    
    file = request.files['file']
    effective_date = request.form.get('effective_date')
    uploader = 'System'  # Default value since uploaded_by field is removed
    
    if file.filename == '':
        flash('No file selected', 'error')
        return redirect(request.url)
    
    if not effective_date:
        flash('Effective date is required', 'error')
        return redirect(request.url)
    
    if file and file.filename.lower().endswith('.csv'):
        try:
            # Read file content
            csv_content = file.read().decode('utf-8')
            
            # Parse and process CSV
            result = parse_csv_content(csv_content, effective_date, uploader)
            
            
            if result['success']:
                flash(f'Successfully processed {result["total_records"]} records! Rates: {result["inserted_count"]}, Business Codes: {result["business_codes_processed"]}, Jurisdictions: {result["jurisdictions_processed"]}', 'success')
            else:
                flash(f'Processed with errors: {len(result["errors"])} errors out of {result["total_records"]} records', 'warning')
            
        except Exception as e:
            logger.error(f"Upload processing error: {str(e)}")
            flash(f'Error processing file: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/rates')
def view_rates():
    """View all tax rates with filtering."""
    try:
        # Get filter parameters
        effective_date = request.args.get('effective_date')
        business_code = request.args.get('business_code')
        region_code = request.args.get('region_code')
        min_rate = request.args.get('min_rate')
        
        # Build query with proper joins to get meaningful names
        query = supabase.table('current_rates').select('*, jurisdictions(*), business_class_codes(*)')
        
        if effective_date:
            # Join with rate_versions to filter by effective_date
            query = query.eq('rate_versions.effective_date', effective_date)
        if business_code:
            query = query.eq('business_code', business_code)
        if region_code:
            # Join with jurisdictions to filter by region_code
            query = query.eq('jurisdictions.city_code', region_code)
        if min_rate:
            query = query.gte('total_rate', float(min_rate))
        
        # Execute query
        result = query.execute()
        rates = result.data or []
        return render_template('rates.html', rates=rates)
        
    except Exception as e:
        logger.error(f"Error fetching rates: {str(e)}")
        flash(f'Error fetching rates: {str(e)}', 'error')
        return render_template('rates.html', rates=[])


@app.route('/api/rates')
def api_rates():
    """API endpoint for rates data."""
    try:
        result = supabase.table('current_rates').select('*, jurisdictions(*), business_class_codes(*)').execute()
        return jsonify(result.data or [])
        
    except Exception as e:
        logger.error(f"API error: {str(e)}")
        return jsonify({'error': str(e)}), 500

# Initialize database on startup (runs in both development and production)
init_database()

if __name__ == '__main__':
    # This only runs for local development (not when using Gunicorn)
    port = int(os.getenv('PORT', 5000))
    logger.info(f"Starting Tax Rates Intake Application on port {port}")
    app.run(debug=True, host='0.0.0.0', port=port)
