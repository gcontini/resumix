output "image" {
  description = "Image the function runs."
  value       = local.image
}

output "url" {
  description = "Public URL of the HTTP trigger: the client's server_url."
  value       = alicloud_fcv3_trigger.main.http_trigger[0].url_internet
}
