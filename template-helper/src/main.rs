use hex::FromHex;
use serde_json::{json, Value};
use std::io::{self, Read};
use zebra_chain::{
    block::{merkle::{AuthDataRoot, Root, AUTH_DIGEST_PLACEHOLDER}, ChainHistoryBlockTxAuthCommitmentHash, ChainHistoryMmrRootHash},
    serialization::ZcashDeserializeInto,
    transaction::Transaction,
};
use zcash_address::ZcashAddress;

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input)?;
    let request: Value = serde_json::from_str(&input)?;
    if let Some(encoded) = request["address"].as_str() {
        let decoded = ZcashAddress::try_from_encoded(encoded)?
            .convert::<zebra_chain::primitives::Address>()
            .map_err(|error| error.to_string())?;
        let transparent = match &decoded {
            zebra_chain::primitives::Address::Transparent(address) =>
                (!address.is_script_hash()).then(|| address.to_string()),
            zebra_chain::primitives::Address::Unified { transparent, .. } =>
                transparent.as_ref().and_then(|address|
                    (!address.is_script_hash()).then(|| address.to_string())),
            _ => None,
        };
        println!("{}", json!({
            "network": decoded.network().to_string(),
            "transparent_p2pkh": transparent,
        }));
        return Ok(());
    }
    let tx_hexes = request["transactions"].as_array().ok_or("missing transactions")?;
    if tx_hexes.is_empty() { return Err("missing coinbase".into()); }
    let mut txs = Vec::with_capacity(tx_hexes.len());
    for tx_hex in tx_hexes {
        let bytes = hex::decode(tx_hex.as_str().ok_or("invalid transaction hex")?)?;
        let tx: Transaction = bytes.zcash_deserialize_into()?;
        txs.push(tx);
    }
    let merkle: Root = txs.iter().map(|tx| tx.hash()).collect();
    let auth: AuthDataRoot = txs.iter().map(|tx| tx.auth_digest().unwrap_or(AUTH_DIGEST_PLACEHOLDER)).collect();
    let chain_history = ChainHistoryMmrRootHash::from_hex(
        request["chainhistoryroot"].as_str().ok_or("missing chainhistoryroot")?
    )?;
    let commitment = ChainHistoryBlockTxAuthCommitmentHash::from_commitments(&chain_history, &auth);
    println!("{}", json!({
        "coinbase_hash": txs[0].hash().to_string(),
        "coinbase_authdigest": txs[0].auth_digest().map(|digest| digest.to_string()),
        "merkleroot": hex::encode(<[u8; 32]>::from(merkle).into_iter().rev().collect::<Vec<_>>()),
        "authdataroot": hex::encode(<[u8; 32]>::from(auth).into_iter().rev().collect::<Vec<_>>()),
        "blockcommitmentshash": commitment.to_string(),
    }));
    Ok(())
}

fn main() {
    if let Err(error) = run() {
        eprintln!("template helper: {error}");
        std::process::exit(1);
    }
}
