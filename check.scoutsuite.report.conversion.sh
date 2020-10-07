#!/bin/bash

RUNNER_DIR=/opt/scoutsuite_runner
REPORT_DIR=/opt/reports.scoutsuite
LOGDIR=$RUNNER_DIR/log
SS_CONVERTER_SCRIPT=$RUNNER_DIR/ss_converter_aws.py

REPORT_BASE=20*-*
LOGFILE=$LOGDIR/collector.scoutsuite_runner.log
PREFIX_REPORT_FILE=report.scoutsuite
PREFIX_REPORT_EXCEPTION=scoutsuite_exceptions_
PREFIX_REPORT_RESULTS=scoutsuite_results_
TIMESTAMP=`date +"%Y-%m-%d %H:%M:%S.%3N%z"`
PROC_NAME="report_conversion_check"

CNUM=0

# get date from folder based on latest file
function get_latest_date() {
	DATE_FOLDER=`find $1 -type f -name 'report.scoutsuite.*.txt' -exec stat \{} --printf="%y\n" \; | sort -n -r | head -n 1`
}

echo "$TIMESTAMP $PROC_NAME: begin checking for missing converted scoutsuite reports" >> $LOGFILE

ts1=`date +%s`

# archive old folders; skip date folder
for FOLDER in `find $REPORT_DIR/$REPORT_BASE -mindepth 1 -maxdepth 1 -mtime +1 -type d `; do

    FOLDER_BASE=`basename $FOLDER | cut -d. -f1`
    FOLDER_TS=`basename $FOLDER | cut -d. -f2-3`

    #echo "$TIMESTAMP DEBUG $PROC_NAME: validating folder ids. folder: $FOLDER base: $FOLDER_BASE timestamp: $FOLDER_TS" >> $LOGFILE

    # check for exceptions
    CHK_REPORT_EXCEPTION=`find $FOLDER -type f -name "$PREFIX_REPORT_EXCEPTION*" `
    if [ -z "$CHK_REPORT_EXCEPTION" ]; then
        echo "$TIMESTAMP WARNING $PROC_NAME: cannot find report exceptions for folder: $FOLDER_BASE date: $FOLDER_TS" >> $LOGFILE
    fi

    # check for results
    CHK_REPORT_RESULTS=`find $FOLDER -type f -name "$PREFIX_REPORT_RESULTS*" `
    if [ -z "$CHK_REPORT_RESULTS" ]; then
        echo "$TIMESTAMP WARNING $PROC_NAME: cannot find report results for folder: $FOLDER_BASE date: $FOLDER_TS" >> $LOGFILE

    else
        get_latest_date $FOLDER
        ORIG_REPORT=$CHK_REPORT_RESULTS
        ORIG_REPORT_FOLDER=`dirname $ORIG_REPORT`

        # extract the aws profile name from the original results file
        [[ "$ORIG_REPORT" =~ scoutsuite_results_(.*)\.js ]]
        EXTRACTED_PROFILE="${BASH_REMATCH[1]}"      

        # check for converted report
        CHK_REPORT_CONVERTED=`find $FOLDER -type f -name "$PREFIX_REPORT_FILE.*" ` 
        if [ -z "$CHK_REPORT_CONVERTED" ] || [ ! -s "$CHK_REPORT_CONVERTED" ] ; then
            echo -e "$TIMESTAMP $PROC_NAME: detected missing or incomplete converted JSON report file. attempting again. folder: $FOLDER_BASE date: $FOLDER_TS target file name: report.scoutsuite.$EXTRACTED_PROFILE.txt" >> $LOGFILE

            # for debugging, skip actual convertion remediation
            #continue
            CHK_FLAG=0
            echo "$TIMESTAMP $PROC_NAME: converting $ORIG_REPORT >> $ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt" >> $LOGFILE
            #echo python3 $SS_CONVERTER_SCRIPT -s "$ORIG_REPORT" -d "$ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt"
            python3 $SS_CONVERTER_SCRIPT -s "$ORIG_REPORT" -d "$ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt"
            CHK_FLAG=$? # return 0 if success

            if [ $CHK_FLAG == 0 ]; then
                CNUM=$((CNUM+1))
                # reset timestamp for easier maintenance
                touch -d "$DATE_FOLDER" $ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt
            else
                echo -e "$TIMESTAMP $PROC_NAME: failed converstion attempt again folder: $FOLDER_BASE  date: $FOLDER_TS  target file name: report.scoutsuite.$EXTRACTED_PROFILE.txt" >> $LOGFILE
            fi
        fi

    fi

done

te1=`date +%s`
duration=$((te1 - ts1))

if [ $CNUM -gt 0 ]; then
    echo "$TIMESTAMP $PROC_NAME: successfully remediated the conversion of $CNUM ScoutSuite reports. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE
fi

