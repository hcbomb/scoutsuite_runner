#/bin/sh

it_only=true
ignore_cloud=true
temp_file=aws_profile_list.txt
role=okta_ro_role
my_csv=aws_account_list.csv

echo "" > $temp_file

IFS=,
printf "skip flags: it_only: %s ignore_cloud: %s\n" $it_only $ignore_cloud
while read -r aws_profile_name aws_account_id ou ou_name status
do
    if [[ "$it_only" = true && "$ou_name" != "itops" ]]; then
        printf "<<< skipping NON-IT OPS account: %s %s\n" $aws_profile_name
        continue

    elif [[ "$status" != ACTIVE* ]]; then
        printf "<<< skipping NON-ACTIVE account: %s %s\n" $aws_profile_name $ou_name
        continue

    elif [[ "$ignore_cloud" = true && ( "$ou_name" == *no_policy* || "$ou_name" == "unmanaged" ) ]]; then
        printf ">>> skipping CLOUD account: %s ou: %s status: %s \n" $aws_profile_name $ou_name $status
        continue
    fi

    printf "*** profile: %s account id: %s ou: %s ou name: %s status; %s\n" $aws_profile_name $aws_account_id $ou $ou_name $status

    # add AWS profile
    aws configure set source_profile Voltron_DCN --profile $aws_profile_name
    aws configure set role_arn arn:aws:iam::$aws_account_id:role/$role --profile $aws_profile_name
    aws configure set region us-east-1 --profile $aws_profile_name

    # add profile temp file for processing
    echo "$aws_profile_name" >> $temp_file

done < "$my_csv"

echo "total aws profiles captured: $(wc -l $temp_file)"


