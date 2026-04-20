#!/bin/bash
# STAR-ASN Automated S3 Backup Script
# Backup Supabase PostgreSQL to AWS S3 daily

set -e

# Configuration
DB_URL="${POSTGRES_URL}"
S3_BUCKET="${S3_BACKUP_BUCKET:-star-asn-backups}"
S3_REGION="${AWS_REGION:-ap-south-1}"
BACKUP_RETENTION_DAYS=30
BACKUP_DIR="/tmp/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/star_asn_backup_$TIMESTAMP.sql"

# Logging
LOG_FILE="/var/log/star_asn_backup.log"
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" >> $LOG_FILE
}

# Error handling
trap 'log "ERROR: Backup failed!"; exit 1' ERR

log "Starting STAR-ASN database backup..."

# Create backup directory
mkdir -p $BACKUP_DIR

# Dump database
log "Dumping PostgreSQL database..."
pg_dump "$DB_URL" --no-password > "$BACKUP_FILE" 2>> $LOG_FILE

# Compress backup
log "Compressing backup..."
gzip "$BACKUP_FILE"
BACKUP_FILE_GZ="$BACKUP_FILE.gz"
BACKUP_SIZE=$(du -h "$BACKUP_FILE_GZ" | cut -f1)

log "Backup size: $BACKUP_SIZE"

# Upload to S3
log "Uploading to S3..."
aws s3 cp "$BACKUP_FILE_GZ" "s3://$S3_BUCKET/daily/$TIMESTAMP/" \
    --region $S3_REGION \
    --storage-class STANDARD_IA \
    --metadata "timestamp=$TIMESTAMP,database=star_asn" \
    2>> $LOG_FILE

log "Successfully uploaded to s3://$S3_BUCKET/daily/$TIMESTAMP/"

# Cleanup local backups older than retention period
log "Cleaning up local backups older than $BACKUP_RETENTION_DAYS days..."
find $BACKUP_DIR -name "star_asn_backup_*.sql.gz" -mtime +$BACKUP_RETENTION_DAYS -delete

# Cleanup S3 backups older than retention period
log "Cleaning up S3 backups older than $BACKUP_RETENTION_DAYS days..."
CUTOFF_DATE=$(date -d "$BACKUP_RETENTION_DAYS days ago" +%s)
aws s3api list-objects-v2 --bucket "$S3_BUCKET" --prefix "daily/" --region $S3_REGION | \
  jq -r '.Contents[] | select(.LastModified | fromdateiso8601 | . < '$CUTOFF_DATE') | .Key' | \
  while read KEY; do
    aws s3 rm "s3://$S3_BUCKET/$KEY" --region $S3_REGION
    log "Deleted old backup: $KEY"
  done

# Verify backup in S3
log "Verifying backup in S3..."
if aws s3api head-object --bucket "$S3_BUCKET" --key "daily/$TIMESTAMP/" --region $S3_REGION > /dev/null 2>&1; then
    log "✅ Backup verification successful!"
else
    log "❌ Backup verification failed!"
    exit 1
fi

# Send notification
log "Sending backup notification..."
curl -X POST "https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK" \
  -H 'Content-Type: application/json' \
  -d "{
    \"text\": \"✅ STAR-ASN Database Backup Successful\",
    \"blocks\": [
      {
        \"type\": \"section\",
        \"text\": {
          \"type\": \"mrkdwn\",
          \"text\": \"*Backup Status:* ✅ Success\n*Size:* $BACKUP_SIZE\n*Timestamp:* $TIMESTAMP\n*Location:* s3://$S3_BUCKET/daily/$TIMESTAMP/\"
        }
      }
    ]
  }" 2>> $LOG_FILE

log "Backup completed successfully!"
exit 0
