#!/bin/bash
SCOUTSUITE=/opt/scoutsuite
RUNNER_DIR=/opt/scoutsuite_runner
REPORT_DIR=/opt/reports.scoutsuite
LOGDIR=$RUNNER_DIR/log

SCOUTSUITE_SCRIPT=$SCOUTSUITE/ScoutSuite/scout.py
GET_ORG_SCRIPT=$RUNNER_DIR/get_org_list.py
SS_CONVERTER_SCRIPT=$RUNNER_DIR/ss_converter_aws.py
PROFILE=$RUNNER_DIR/aws_profile_list.txt
PROFILE_BUILDER_SCRIPT=$RUNNER_DIR/aws_configurate.sh
LOGFILE=$LOGDIR/collector.scoutsuite_runner.log
RABBITFILE=$RUNNER_DIR/rabbit.txt # used to easily track newly generated Scoutsuite report files

ORIG_AWS_PROFILE="Voltron_DCN"
TIMESTAMP=`date +"%Y-%m-%d %H:%M:%S.%3N%z"`
TIMESTAMP_TAG=`date +"%Y-%m-%d.%H_%M_%S.%3N%z"`
DATESTAMP_TAG=`date +"%Y-%m-%d"`

MAX_NPROC=10
NUM=0
TOTAL=0
CNUM=0

# Throttling params
MAX_WORKERS=2
MAX_RATE=5 # describe/list API calls per second

function queue {
    QUEUE="$QUEUE $1"
    NUM=$(($NUM+1))
}
function regeneratequeue {
    OLDREQUEUE=$QUEUE
    QUEUE=""
    NUM=0
    for PID in $OLDREQUEUE
    do
        if [ -d /proc/$PID  ] ; then
            QUEUE="$QUEUE $PID"
            NUM=$(($NUM+1))
        fi
    done
}
function checkqueue {
    OLDCHQUEUE=$QUEUE
    for PID in $OLDCHQUEUE
    do
        if [ ! -d /proc/$PID ] ; then
            regeneratequeue # at least one PID has finished
            break
        fi
    done
}

if [ ! -d $LOGDIR ] || [ ! -d $LOGDIR/$DATESTAMP_TAG ]; then
    mkdir -p $LOGDIR
    mkdir -p $LOGDIR/$DATESTAMP_TAG
fi
if [ ! -d $REPODIR ]; then
    mkdir -p $REPODIR
    mkdir -p $REPORT_DIR/$DATESTAMP_TAG
fi

# release the rabbit
touch $RABBITFILE

source $SCOUTSUITE/venv/bin/activate
echo "$TIMESTAMP creating aws account list from org..." >> $LOGFILE
ts1=`date +%s`
echo "executing: python3 $GET_ORG_SCRIPT -p $ORIG_AWS_PROFILE" >> $LOGFILE
python3 $GET_ORG_SCRIPT -p $ORIG_AWS_PROFILE >> $LOGFILE
te1=`date +%s`
duration=$((te1 - ts1))

echo "$TIMESTAMP aws account list created, proceeding to build aws config. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE

ts1=`date +%s`
bash $PROFILE_BUILDER_SCRIPT >> $LOGFILE
te1=`date +%s`
duration=$((te1 - ts1))

echo "$TIMESTAMP aws config, proceeding to run botorator scoutsuite rate limiter. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE

ts2=`date +%s`
#PROFILE=$RUNNER_DIR/test_it.aws.profile.txt
echo "profile path: $PROFILE"
for AWS_PROFILE in `cat $PROFILE`; do
    echo "$TIMESTAMP processing AWS_PROFILE=$AWS_PROFILE" >> $LOGFILE

    TOTAL=$((TOTAL+1))
# print executed scoutsuite run into debug log
    echo "python3 $SCOUTSUITE_SCRIPT aws --profile $AWS_PROFILE --max-workers $MAX_WORKERS --max-rate $MAX_RATE --report-dir $REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG --report-name $AWS_PROFILE -f"  >> $LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log 2>&1

    python3 $SCOUTSUITE_SCRIPT aws --profile "$AWS_PROFILE" --max-workers $MAX_WORKERS --max-rate $MAX_RATE --report-dir "$REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG" --report-name "$AWS_PROFILE" -f >> "$LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log" 2>&1 &
# no rate limiting
    #python3 $SCOUTSUITE_SCRIPT aws --profile $AWS_PROFILE --report-dir $REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG --report-name $AWS_PROFILE >> $LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log 2>&1
    PID=$!
    if [[ ! -z "$PID" ]]; then
        echo "$TIMESTAMP outputting to filename=$LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log aws profile: $AWS_PROFILE count: $TOTAL pid: $PID" >> $LOGFILE
        queue $PID

        while [ $NUM -ge $MAX_NPROC ]; do
            checkqueue
            sleep 0.01
        done
    fi

    echo "$TIMESTAMP processing scanning AWS_PROFILE=$AWS_PROFILE" >> $LOGFILE

done

te2=`date +%s`
duration=$((te2 - ts2))
duration2=$((te2 - ts1))
echo -e "$TIMESTAMP ScoutSuite runner job complete. total time elapsed: $(($duration / 60))  min and $(($duration % 60)) sec\t$(($duration2 / 60))  min and $(($duration2 % 60)) sec" >> $LOGFILE

# convert all newly generated ScoutSuite report files into Splunk-friendly data events
for REPORT in `find $REPORT_DIR -cnewer $RABBITFILE -type f -name 'scoutsuite_results_*.js'`; do
    ORIG_REPORT_FOLDER=`dirname $REPORT`
    # extract the aws profile name from the original results file
    [[ "$REPORT" =~ report.scoutsuite\.(.*)\.txt ]]
    EXTRACTED_PROFILE="${BASH_REMATCH[1]}"

    echo "$TIMESTAMP converting $REPORT >> $ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt" >> $LOGFILE
    python3 $SS_CONVERTER_SCRIPT -s "$REPORT" -d "$ORIG_REPORT_FOLDER/report.scoutsuite.$EXTRACTED_PROFILE.txt"
    CNUM=$((CNUM+1))
done

echo "$TIMESTAMP successfully converted $CNUM ScoutSuite reports" >> $LOGFILE

