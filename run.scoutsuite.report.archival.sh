#!/bin/bash

RUNNER_DIR=/opt/scoutsuite_runner
REPORT_DIR=/opt/reports.scoutsuite
LOGDIR=$RUNNER_DIR/log

LIMIT_ARCHIVE=10
LIMIT_DELETE=30
REPORT_BASE=20*-*
PREFIX_ARCHIVE=archive.scoutsuite
LOGFILE=$LOGDIR/collector.scoutsuite_runner.log
TIMESTAMP=`date +"%Y-%m-%d %H:%M:%S.%3N%z"`
PROC_NAME="report_archival"

# get date from folder based on latest file
function get_latest_date() {
    DATE_FOLDER=`find $1 -type f -name 'report.scoutsuite.*.txt' -exec stat \{} --printf="%y\n" \; | sort -n -r | head -n 1`
}

echo "$TIMESTAMP $PROC_NAME: archiving: begin archiving scoutsuite reports" >> $LOGFILE

ts1=`date +%s`

# archive old folders
for FOLDER in `find $REPORT_DIR -ctime +$LIMIT_ARCHIVE -type d -name "$REPORT_BASE" `; do

    get_latest_date $FOLDER
    FOLDER_NAME=`basename $FOLDER`
    ARCHIVE_NAME="${PREFIX_ARCHIVE}.${FOLDER_NAME}.tgz"
    FILE_COUNT=`find $REPORT_DIR -type f | wc -l`
    ARCHIVE_FILE="${REPORT_DIR}/${ARCHIVE_NAME}"

    echo -e "$TIMESTAMP $PROC_NAME: archiving: folder: $FOLDER_NAME\tdate: $DATE_FOLDER \tarchive name: $ARCHIVE_FILE\tfile count: $FILE_COUNT" >> $LOGFILE

    CHK_FLAG=0
    cd $REPORT_DIR
    #echo "tar -czf $ARCHIVE_FILE $FOLDER_NAME"
    tar -czf $ARCHIVE_FILE $FOLDER_NAME
    CHK_FLAG=$? # return 0 if success

    if [ $CHK_FLAG == 0 ]; then
        touch -d "$DATE_FOLDER" $ARCHIVE_FILE
        
        # if successful archive, then delete folder
        rm -rf $FOLDER_NAME
    else
        echo -e "$TIMESTAMP $PROC_NAME: archiving: failed to archive folder: $FOLDER_NAME ; skipping archiving" >> $LOGFILE
    fi

done

te1=`date +%s`
duration=$((te1 - ts1))

echo "$TIMESTAMP $PROC_NAME: archiving: completed archiving scoutsuite reports. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE

# delete
DELETE_LIST=`find $REPORT_DIR -ctime +$LIMIT_DELETE -type f -name "$REPORT_BASE" `
echo "$TIMESTAMP $PROC_NAME: archiving: begin deleting scoutsuite archived reports: $DELETE_LIST" >> $LOGFILE
find $REPORT_DIR -ctime +$LIMIT_DELETE -type f -name "$REPORT_BASE" -delete
CHK_FLAG=$? # return 0 if success

if [ $CHK_FLAG != 0 ]; then
    echo -e "$TIMESTAMP $PROC_NAME: archiving: failed to delete all expired folders. please validate report files: $REPORT_DIR" >> $LOGFILE
fi

