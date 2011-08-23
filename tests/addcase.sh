#!/bin/sh

if [ $# -ne 2 ]; then
  echo "Usage: addcase.sh <case-name> <case-ksfile>"
  exit 1
fi

CaseName=$1
CaseKs=$2

diff -upN ./mic_cases/base/test.ks ${CaseKs} > ks.p

cp ./mic_cases/base/test.conf conf_new
vi conf_new
diff -upN ./mic_cases/base/test.conf conf_new > conf.p
rm -f conf_new

cd ./mic_cases
mkdir test-${CaseName}
cd test-${CaseName}

mv ../../ks.p .
mv ../../conf.p .
vi options
vi expect

echo 'Ks diff:'
cat ks.p

echo 'Config diff:'
cat conf.p
