import pulumi
import pulumi_aws as aws
import pulumi_synced_folder as synced_folder

S3_ORIGIN_ID = "AppS3Origin"

config = pulumi.Config()
path = config.get("path") or "./www"

DOMAIN = config.get("domain") # 'vandersonsantos.org'
SUB_DOMAIN = config.get("subdomain") # 'portfolio'
HOST_DOMAIN = f"{SUB_DOMAIN}.{DOMAIN}"

# ---------- Bucket configuraition --
# S3 Bucket
bucket_v2 = aws.s3.BucketV2("bucketV2",
    bucket=HOST_DOMAIN,
    tags={
        "Name": HOST_DOMAIN,
    }
)

ownership_controls = aws.s3.BucketOwnershipControls(
    "ownership-controls",
    bucket=bucket_v2.bucket,
    rule={
        "object_ownership": "ObjectWriter",
    },
)

public_access_block = aws.s3.BucketPublicAccessBlock(
    "public-access-block",
    bucket=bucket_v2.bucket,
    block_public_acls=False,
)

bucket_folder = synced_folder.S3BucketFolder(
    "bucket-folder",
    acl="public-read",
    bucket_name=bucket_v2.bucket,
    path=path,
    opts=pulumi.ResourceOptions(
        depends_on=[
            ownership_controls, 
            public_access_block
        ]
    ),
)

# ---------- ACM SSL certificate --
# ACM SSL Certificate for CloudFront Distribution
app_cert = aws.acm.Certificate("cert",
    domain_name=HOST_DOMAIN,
    tags={
        "Environment": pulumi.get_stack(),
    },
    validation_method="DNS",
)

# ---------- Route53 configuration --
# Route53 records
hosted_zone_id = aws.route53.get_zone(
    name=DOMAIN, 
    # async_=True
).zone_id

cert_record = aws.route53.Record("cert",
    zone_id=hosted_zone_id,
    name=app_cert.domain_validation_options[0].resource_record_name,
    type=app_cert.domain_validation_options[0].resource_record_type,
    ttl=300,
    records=[app_cert.domain_validation_options[0].resource_record_value],
)

certificate_validation = aws.acm.CertificateValidation("certificateValidation",
    certificate_arn=app_cert.arn,
    validation_record_fqdns=[cert_record.fqdn],
)

# ---------- CloudFront configuration --
oai = aws.cloudfront.OriginAccessIdentity("oai",
    comment="OAI for App bucket and cloudfront distribution",
)


s3_distribution = aws.cloudfront.Distribution("s3Distribution",
    origins=[{
        "domain_name": bucket_v2.bucket_regional_domain_name,
        "origin_id": S3_ORIGIN_ID,
        "s3_origin_config": {
            "origin_access_identity": oai.cloudfront_access_identity_path,
        }
    }],
    enabled=True,
    is_ipv6_enabled=True,
    comment="portfolio",
    default_root_object="index.html",
    aliases=[HOST_DOMAIN],
    default_cache_behavior={
        "allowed_methods": ["GET", "HEAD", "OPTIONS"],
        "cached_methods": ["GET", "HEAD"],
        "target_origin_id": S3_ORIGIN_ID,
        "forwarded_values": {
            "query_string": False,
            "cookies": {
                "forward": "none",
            },
        },
        "viewer_protocol_policy": "allow-all",
        "min_ttl": 0,
        "default_ttl": 3600,
        "max_ttl": 86400,
    },
    ordered_cache_behaviors=[{
        "path_pattern": "/*",
        "allowed_methods": ["GET", "HEAD", "OPTIONS"],
        "cached_methods": ["GET", "HEAD"],
        "target_origin_id": S3_ORIGIN_ID,
        "forwarded_values": {
            "query_string": False,
            "cookies": {
                "forward": "none",
            },
        },
        "min_ttl": 0,
        "default_ttl": 3600,
        "max_ttl": 86400,
        "compress": True,
        "viewer_protocol_policy": "redirect-to-https",
    }],
    price_class="PriceClass_All",
    restrictions={
        "geo_restriction": {
            "restriction_type": "none",
        },
    },
    tags={
        "Environment": pulumi.get_stack(),
    },
    viewer_certificate={
        "acm_certificate_arn": app_cert.arn,
        "cloudfront_default_certificate": False,
        "minimum_protocol_version": 'TLSv1.2_2021',
        "ssl_support_method": 'sni-only',
    },
)

# DNS record for CloudFront distribution
app_record = aws.route53.Record("app",
    zone_id=hosted_zone_id,
    name=app_cert.domain_validation_options[0].domain_name,
    type="CNAME",
    ttl=300,
    records=[s3_distribution.domain_name],
)

# S3 Bucket Policy
s3_policy_doc = aws.iam.get_policy_document_output(
    statements=[{
        "actions": ["s3:GetObject"],
        "resources": [
            bucket_v2.arn,
            pulumi.Output.concat(bucket_v2.arn, "/*")
            # pulumi.concat(f"{bucket_v2.arn}","/*"),
            # f"{bucket_v2.arn}/*"
        ],
        "principals": [{
            "type": "AWS",
            "identifiers": [oai.iam_arn],
        }],
    }]
)

s3_policy = aws.s3.BucketPolicy("s3Policy",
    bucket=bucket_v2.id,
    policy=s3_policy_doc.apply(lambda doc: doc.json),
)
