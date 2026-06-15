import pandas as pd
from core.database import db
import math

def seed_assets_from_ods(ods_path='Carteira - Rafael Mascarenhas.ods'):
    print(f"Reading {ods_path}...")
    df = pd.read_excel(ods_path, engine='odf', sheet_name='DADOS')

    # Strip column names just in case there are trailing spaces in the ODS headers
    df.columns = df.columns.str.strip()

    # Filter out empty rows just in case
    df = df.dropna(subset=['CÓDIGO', 'NOME'])

    conn = db.get_assets_connection()
    cursor = conn.cursor()

    print(f"Found {len(df)} assets. Inserting into database...")

    inserted = 0
    updated = 0
    for _, row in df.iterrows():
        ticker = str(row['CÓDIGO']).strip()
        nome = str(row['NOME']).strip()
        
        # Handle nan values for optional fields securely
        image = str(row.get('IMAGEM', '')).strip() if pd.notna(row.get('IMAGEM')) else ''
        cnpj = str(row.get('CNPJ', '')).strip() if pd.notna(row.get('CNPJ')) else ''
        
        setor = str(row.get('SETOR ECONÔMICO', 'Outros')).strip()
        if pd.isna(row.get('SETOR ECONÔMICO')):
            setor = 'Outros'
            
        subsetor = str(row.get('SUBSETOR', '')).strip() if pd.notna(row.get('SUBSETOR')) else ''
        
        # In the original spreadsheet, the column is often 'SEGMENTO / ADM / PAÍS' or 'SEGMENTO'
        segmento_val = row.get('SEGMENTO / ADM / PAÍS', row.get('SEGMENTO', ''))
        segmento = str(segmento_val).strip() if pd.notna(segmento_val) else ''

        tipo = str(row.get('TIPO', 'Ação')).strip()
        if pd.isna(row.get('TIPO')):
            tipo = 'Ação'

        # Insert or replace
        cursor.execute("SELECT ticker FROM assets WHERE ticker = ?", (ticker,))
        if cursor.fetchone():
            cursor.execute('''
                UPDATE assets
                SET name = ?, image = ?, cnpj = ?, sector = ?, sub_sector = ?, segment = ?, asset_type = ?
                WHERE ticker = ?
            ''', (nome, image, cnpj, setor, subsetor, segmento, tipo, ticker))
            updated += 1
        else:
            cursor.execute('''
                INSERT INTO assets (ticker, name, image, cnpj, sector, sub_sector, segment, asset_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (ticker, nome, image, cnpj, setor, subsetor, segmento, tipo))
            inserted += 1

    conn.commit()
    conn.close()

    print(f"Done! Inserted {inserted} new assets and updated {updated} existing ones.")

if __name__ == "__main__":
    db.init_assets_db() # Ensure assets table exists
    seed_assets_from_ods()
