# Alibaba Cloud deployment

The server as a Function Compute 3.0 function, and the Container Registry
Personal Edition repository its image is built into.

| Managed here | Console only — no API reaches it |
|---|---|
| namespace and repository | the Personal Edition instance (`crpi-…`) |
| function, alias, HTTP trigger, reserved concurrency | the registry login password |
| | the GitHub source and the build rules (`main` → `latest`, `vX.Y.Z` → `X.Y.Z`) |
| | rotating the trigger token |

## Run it

```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID=... ALIBABA_CLOUD_ACCESS_KEY_SECRET=...
cp terraform.tfvars.example terraform.tfvars   # then fill it in
terraform init
terraform plan
terraform apply
```

The first plan adopts the resources made by hand in the console
(`imports.tf`): **6 to import, 1 to change**. The change only records which
environment variables are secret; the values are unchanged and nothing is sent
to the function. Every plan after that should say *No changes*.

## A release

1. In the console, add the build rule for the new tag (`vX.Y.Z` → `X.Y.Z`)
   and wait for the build.
2. Set `image_tag` in `terraform.tfvars`, then `terraform apply`.

## What to know

- **`terraform.tfvars` and the state hold the provider keys and the trigger
  token in clear text.** Both are gitignored; treat them like `.env`. The import
  plan prints the trigger token once, because the provider does not mark that
  field sensitive.
- **The trigger token is set once, when the trigger is created.** FC stamps
  every token with an id and timestamps, so Terraform ignores the trigger's
  configuration after that. Rotate the token in the console.
- **Renaming the function replaces it**, and the trigger URL — the clients'
  `server_url` — changes with it.
- **From scratch**, in an account with none of this: create the Personal
  Edition instance and its password in the console, delete `imports.tf`, run
  `terraform apply -target=alicloud_cr_repo.main`, set up the GitHub build and
  let it push a tag, then run `terraform apply`.
