#!/bin/bash
SCOUTSUITE=/opt/scoutsuite
RUNNER_DIR=/opt/scoutsuite_runner
REPORT_DIR=/opt/reports.scoutsuite
LOGDIR=$RUNNER_DIR/log

SCOUTSUITE_SCRIPT=$SCOUTSUITE/ScoutSuite/scout.py
GET_ORG_SCRIPT=$RUNNER_DIR/get_org_list.py
PROFILE=$RUNNER_DIR/aws_profile_list.txt
PROFILE_BUILDER_SCRIPT=$RUNNER_DIR/aws_configurate.sh
LOGFILE=$LOGDIR/collector.botorator.log

ORIG_AWS_PROFILE="Voltron_DCN"
TIMESTAMP=`date +"%Y-%m-%d %H:%M:%S.%3N%z"`
TIMESTAMP_TAG=`date +"%Y-%m-%d.%H_%M_%S.%3N%z"`
DATESTAMP_TAG=`date +"%Y-%m-%d"`

MAX_NPROC=10
NUM=0
TOTAL=0

# Throttling params
MAX_WORKERS=2
MAX_RATE=10 # describe/list API calls per second

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

source /opt/scoutsuite/venv/bin/activate
echo "$TIMESTAMP creating aws account list from org..." >> $LOGFILE
ts1=`date +%s`
echo "executing: python3 $GET_ORG_SCRIPT -p $ORIG_AWS_PROFILE" >> $LOGFILE
#python3 $GET_ORG_SCRIPT -p $ORIG_AWS_PROFILE >> $LOGFILE
te1=`date +%s`
duration=$((te1 - ts1))

echo "$TIMESTAMP aws account list created, proceeding to build aws config. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE

ts1=`date +%s`
#bash $PROFILE_BUILDER_SCRIPT >> $LOGFILE
te1=`date +%s`
duration=$((te1 - ts1))

echo "$TIMESTAMP aws config, proceeding to run botorator scoutsuite rate limiter. elapsed: $(($duration / 60)) min and $(($duration % 60)) sec" >> $LOGFILE

ts2=`date +%s`
PROFILE=$SCOUTSUITE/test_it.aws.profile.txt
for AWS_PROFILE in `cat $PROFILE`; do
    echo "$TIMESTAMP processing AWS_PROFILE=$AWS_PROFILE" >> $LOGFILE

    # send error output to logfile
    while read i
    do
        TOTAL=$((TOTAL+1))
        echo "$TIMESTAMP outputting to filename=$LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log aws profile: $AWS_PROFILE count: $TOTAL" >> $LOGFILE
		echo "python3 $SCOUTSUITE_SCRIPT aws --profile $AWS_PROFILE --report-dir $REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG --report-name $AWS_PROFILE " >> $LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log 2>&1 
		exit
        python3 $SCOUTSUITE_SCRIPT aws --profile $AWS_PROFILE --max-workers $MAX_WORKERS --max-rate $MAX_RATE --report-dir $REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG --report-name $AWS_PROFILE >> $LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log 2>&1
        #python3 $SCOUTSUITE_SCRIPT aws --profile $AWS_PROFILE --report-dir $REPORT_DIR/$DATESTAMP_TAG/$AWS_PROFILE.$TIMESTAMP_TAG --report-name $AWS_PROFILE >> $LOGDIR/$DATESTAMP_TAG/scoutsuite.$AWS_PROFILE.$TIMESTAMP_TAG.log 2>&1
        PID=$!
        queue $PID

        while [ $NUM -ge $MAX_NPROC ]; do
            checkqueue
            sleep 0.01
        done

    te2=`date +%s`
    duration=$((te2 - ts2))
    duration2=$((te2 - ts1))
    echo "$TIMESTAMP processing scanning AWS_PROFILE=$AWS_PROFILE" >> $LOGFILE
    echo -e "$TIMESTAMP completed AWS_PROFILE=$AWS_PROFILE. elapsed ( only): $(($duration / 60))  min and $(($duration % 60)) sec\t$(($duration2 / 60))  min and $(($duration2 % 60)) sec" >> $LOGFILE

    done < $PROFILE
done

echo "$TIMESTAMP ScoutScout rate limiter job complete." >> $LOGFILE


