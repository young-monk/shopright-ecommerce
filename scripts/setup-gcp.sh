#!/usr/bin/env bash
# One-time GCP setup: WIF, Terraform state bucket, GitHub secrets
# Usage: ./scripts/setup-gcp.sh
set -euo pipefail

PROJECT_ID="project-4e7965a7-ae62-4cc9-b93"
REGION="us-central1"
GITHUB_ORG="young-monk"
GITHUB_REPO="shopright-ecommerce"
SA_NAME="shopright-github-actions"
POOL_ID="shopright-github-pool"
PROVIDER_ID="shopright-github-provider"
TF_BUCKET="shopright-tf-state"

echo "==> Authenticating..."
gcloud config set project "$PROJECT_ID"

echo "==> Enabling required APIs..."
gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  cloudresourcemanager.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com

echo "==> Creating Terraform state bucket..."
if ! gsutil ls -b "gs://$TF_BUCKET" &>/dev/null; then
  gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://$TF_BUCKET"
  gsutil versioning set on "gs://$TF_BUCKET"
  echo "    Created gs://$TF_BUCKET"
else
  echo "    gs://$TF_BUCKET already exists"
fi

echo "==> Creating service account..."
if ! gcloud iam service-accounts describe "$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com" &>/dev/null; then
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="ShopRight GitHub Actions"
fi

SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

echo "==> Granting roles to service account..."
for ROLE in \
  roles/run.admin \
  roles/artifactregistry.admin \
  roles/storage.admin \
  roles/iam.serviceAccountUser \
  roles/cloudsql.admin \
  roles/secretmanager.admin \
  roles/bigquery.admin \
  roles/compute.networkAdmin \
  roles/vpcaccess.admin \
  roles/serviceusage.serviceUsageAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="$ROLE" \
    --condition=None --quiet
done

echo "==> Setting up Workload Identity Federation..."
if ! gcloud iam workload-identity-pools describe "$POOL_ID" --location=global &>/dev/null; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --location=global \
    --display-name="GitHub Actions Pool"
fi

POOL_NAME=$(gcloud iam workload-identity-pools describe "$POOL_ID" \
  --location=global --format="value(name)")

if ! gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --location=global --workload-identity-pool="$POOL_ID" &>/dev/null; then
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --location=global \
    --workload-identity-pool="$POOL_ID" \
    --display-name="GitHub Provider" \
    --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
    --issuer-uri="https://token.actions.githubusercontent.com"
fi

echo "==> Binding service account to GitHub repo..."
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL_NAME}/attribute.repository/${GITHUB_ORG}/${GITHUB_REPO}" \
  --quiet

WIF_PROVIDER="${POOL_NAME}/providers/$PROVIDER_ID"

echo "==> Setting GitHub secrets..."
gh secret set WIF_PROVIDER     --body "$WIF_PROVIDER"   -R "$GITHUB_ORG/$GITHUB_REPO"
gh secret set WIF_SERVICE_ACCOUNT --body "$SA_EMAIL"    -R "$GITHUB_ORG/$GITHUB_REPO"

echo ""
echo "==> Almost done! Set these two secrets manually:"
echo ""
echo "    gh secret set DB_PASSWORD  --body 'YOUR_DB_PASSWORD'  -R $GITHUB_ORG/$GITHUB_REPO"
echo "    gh secret set JWT_SECRET   --body 'YOUR_JWT_SECRET'   -R $GITHUB_ORG/$GITHUB_REPO"
echo ""
echo "==> Then run Terraform:"
echo "    cd infra/terraform"
echo "    terraform init"
echo "    terraform apply -var-file=prod.tfvars -var='db_password=YOUR_DB_PASSWORD' -var='jwt_secret=YOUR_JWT_SECRET'"
echo ""
echo "==> Done! After terraform apply, push any commit to main to trigger deployment."
