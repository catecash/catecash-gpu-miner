use std::io::{self, Read};

use ripemd::Ripemd160;
use secp256k1::{PublicKey, SecretKey};
use sha2::{Digest, Sha256};

fn checked_address(wif: &str, network: &str) -> Result<String, &'static str> {
    let (wif_prefix, address_prefix) = match network {
        "catecash-mainnet" => (0xd2, [0x06, 0x84]),
        "catecash-testnet" => (0xd3, [0x07, 0x84]),
        "catecash-devnet" => (0xf0, [0x1f, 0xc0]),
        _ => return Err("unsupported network"),
    };
    let decoded = bs58::decode(wif).into_vec().map_err(|_| "invalid WIF encoding")?;
    if decoded.len() != 38 || decoded[0] != wif_prefix || decoded[33] != 1 {
        return Err("WIF network or compression flag does not match");
    }
    let check = Sha256::digest(Sha256::digest(&decoded[..34]));
    if decoded[34..] != check[..4] {
        return Err("WIF checksum is invalid");
    }
    let secret_bytes: [u8; 32] = decoded[1..33].try_into().map_err(|_| "invalid private key")?;
    let secret = SecretKey::from_secret_bytes(secret_bytes).map_err(|_| "invalid private key")?;
    let public = PublicKey::from_secret_key(&secret).serialize();
    let hash = Ripemd160::digest(Sha256::digest(public));
    let mut payload = Vec::with_capacity(26);
    payload.extend_from_slice(&address_prefix);
    payload.extend_from_slice(&hash);
    let checksum = Sha256::digest(Sha256::digest(&payload));
    payload.extend_from_slice(&checksum[..4]);
    Ok(bs58::encode(payload).into_string())
}

fn main() {
    let network = match std::env::args().nth(1) {
        Some(value) => value,
        None => {
            eprintln!("network is required");
            std::process::exit(2);
        }
    };
    let mut input = String::new();
    if io::stdin().read_to_string(&mut input).is_err() {
        eprintln!("could not read wallet input");
        std::process::exit(2);
    }
    match checked_address(input.trim(), &network) {
        Ok(address) => println!("{address}"),
        Err(message) => {
            eprintln!("{message}");
            std::process::exit(1);
        }
    }
}
