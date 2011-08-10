#!/bin/sh

if [ $# -ne 2 ]; then
  echo "Usage addcase.sh <case-name> <case-ksfile>"
  exit 1
fi

CaseName=$1
CaseKs=$2

diff -upN ./mic_cases/base/test.ks ${CaseKs} > ks.p

cd ./mic_cases
mkdir test-${CaseName}
cd test-${CaseName}

mv ../../ks.p .
vi options
vi expect

echo 'Ks diff:'
cat ks.p
