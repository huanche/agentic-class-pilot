import {
  CreateBucketCommand,
  DeleteObjectCommand,
  GetObjectCommand,
  HeadBucketCommand,
  PutObjectCommand,
  S3Client,
} from '@aws-sdk/client-s3';

type ObjectStorageMode = 'database' | 'minio';

let client: S3Client | undefined;
let bucketReady: Promise<void> | undefined;

export function getCourseObjectStorageMode(): ObjectStorageMode {
  const mode = (process.env.COURSE_OBJECT_STORAGE_MODE || 'database').trim().toLowerCase();
  if (mode !== 'database' && mode !== 'minio') {
    throw new Error(`COURSE_OBJECT_STORAGE_MODE must be 'database' or 'minio', got '${mode}'`);
  }
  return mode;
}

export function isCourseObjectStorageEnabled() {
  return getCourseObjectStorageMode() === 'minio';
}

function configuration() {
  const endpoint = process.env.COURSE_OBJECT_STORAGE_ENDPOINT?.trim();
  const bucket = process.env.COURSE_OBJECT_STORAGE_BUCKET?.trim();
  const accessKeyId = process.env.COURSE_OBJECT_STORAGE_ACCESS_KEY?.trim();
  const secretAccessKey = process.env.COURSE_OBJECT_STORAGE_SECRET_KEY?.trim();
  if (!endpoint || !bucket || !accessKeyId || !secretAccessKey) {
    throw new Error(
      'MinIO mode requires COURSE_OBJECT_STORAGE_ENDPOINT, BUCKET, ACCESS_KEY and SECRET_KEY',
    );
  }
  return {
    endpoint,
    bucket,
    region: process.env.COURSE_OBJECT_STORAGE_REGION?.trim() || 'us-east-1',
    forcePathStyle: process.env.COURSE_OBJECT_STORAGE_FORCE_PATH_STYLE !== 'false',
    credentials: { accessKeyId, secretAccessKey },
  };
}

function objectClient() {
  if (client) return client;
  const config = configuration();
  client = new S3Client({
    endpoint: config.endpoint,
    region: config.region,
    forcePathStyle: config.forcePathStyle,
    credentials: config.credentials,
  });
  return client;
}

async function ensureBucket() {
  if (bucketReady) return bucketReady;
  bucketReady = (async () => {
    const config = configuration();
    try {
      await objectClient().send(new HeadBucketCommand({ Bucket: config.bucket }));
    } catch (error) {
      const status = (error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode;
      const name = (error as { name?: string }).name;
      if (status !== 404 && name !== 'NotFound' && name !== 'NoSuchBucket') throw error;
      await objectClient().send(new CreateBucketCommand({ Bucket: config.bucket }));
    }
  })().catch((error) => {
    bucketReady = undefined;
    throw error;
  });
  return bucketReady;
}

function safeKey(key: string) {
  const normalized = key.replace(/\\/g, '/').replace(/^\/+/, '');
  if (!normalized || normalized.split('/').includes('..')) throw new Error('Invalid object key');
  return normalized;
}

export async function putCourseObject(key: string, bytes: Buffer, contentType: string) {
  await ensureBucket();
  const config = configuration();
  await objectClient().send(
    new PutObjectCommand({
      Bucket: config.bucket,
      Key: safeKey(key),
      Body: bytes,
      ContentType: contentType,
    }),
  );
}

export async function readCourseObject(key: string): Promise<Buffer | null> {
  await ensureBucket();
  const config = configuration();
  try {
    const result = await objectClient().send(
      new GetObjectCommand({ Bucket: config.bucket, Key: safeKey(key) }),
    );
    if (!result.Body) return null;
    return Buffer.from(await result.Body.transformToByteArray());
  } catch (error) {
    const status = (error as { $metadata?: { httpStatusCode?: number } }).$metadata?.httpStatusCode;
    const name = (error as { name?: string }).name;
    if (status === 404 || name === 'NoSuchKey' || name === 'NotFound') return null;
    throw error;
  }
}

export async function deleteCourseObject(key: string) {
  await ensureBucket();
  const config = configuration();
  await objectClient().send(
    new DeleteObjectCommand({ Bucket: config.bucket, Key: safeKey(key) }),
  );
}
