
from flask import Flask, jsonify, request
import redis
import os
import psycopg2
import json
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# ==========================================
# 1. KONEKSI REDIS
# ==========================================

redis_host = os.environ.get("REDIS_HOST", "localhost")

r = redis.Redis(
    host=redis_host,
    port=6379,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2
)


# ==========================================
# 2. KONEKSI POSTGRESQL
# ==========================================

def get_db_connection():
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database="db_krs_kampus",
        user="krs_admin",
        password="krs_password"
    )


# ==========================================
# 3. FUNGSI REDIS DENGAN FALLBACK
# ==========================================

def get_krs_cache():
    try:
        return r.get("krs_all")
    except redis.RedisError:
        app.logger.warning(
            "Redis tidak tersedia. Menggunakan PostgreSQL."
        )
        return None


def set_krs_cache(data):
    try:
        r.setex("krs_all", 60, json.dumps(data))
    except redis.RedisError:
        app.logger.warning(
            "Redis tidak tersedia. Cache tidak disimpan."
        )


def clear_krs_cache():
    try:
        r.delete("krs_all")
    except redis.RedisError:
        app.logger.warning(
            "Redis tidak tersedia. Cache tidak dapat dibersihkan."
        )


# ==========================================
# 4. HALAMAN UTAMA
# ==========================================

@app.route("/")
def home():
    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT version();")
        db_version = cur.fetchone()[0]

        cur.close()

        try:
            r.incr("hits")
            hit_count = r.get("hits")
            redis_status = "connected"

        except redis.RedisError:
            hit_count = "Redis tidak tersedia"
            redis_status = "unavailable"

        return jsonify({
            "status": "success",
            "message": "Sistem KRS Kampus Berjalan Normal di Docker!",
            "database_info": db_version,
            "redis_status": redis_status,
            "visitor_or_transaction_hits": hit_count
        })

    except Exception as e:
        app.logger.exception("Pemeriksaan layanan gagal.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 5. READ - MENAMPILKAN SELURUH DATA KRS
# ==========================================

@app.route("/krs", methods=["GET"])
def get_all_krs():

    # Memeriksa cache Redis terlebih dahulu
    cached_data = get_krs_cache()

    if cached_data:
        try:
            data = json.loads(cached_data)

            return jsonify({
                "status": "success",
                "source": "Redis Cache",
                "total_data": len(data),
                "data": data
            })

        except (TypeError, ValueError):
            pass

    conn = None

    try:
        conn = get_db_connection()

        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT
                k.id,
                m.nim,
                m.nama,
                mk.kode_mk,
                mk.nama_mk,
                mk.sks,
                k.tahun_ajaran,
                k.semester_akademik,
                k.tanggal_pengambilan
            FROM krs k
            JOIN mahasiswa m
                ON k.mahasiswa_id = m.id
            JOIN mata_kuliah mk
                ON k.mata_kuliah_id = mk.id
            ORDER BY k.id
        """)

        rows = cur.fetchall()

        result = []

        for row in rows:
            item = dict(row)

            if item["tanggal_pengambilan"]:
                item["tanggal_pengambilan"] = str(
                    item["tanggal_pengambilan"]
                )

            result.append(item)

        cur.close()

        # Menyimpan hasil query ke Redis jika tersedia
        set_krs_cache(result)

        return jsonify({
            "status": "success",
            "source": "PostgreSQL",
            "total_data": len(result),
            "data": result
        })

    except Exception as e:
        app.logger.exception("Gagal mengambil data KRS.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 6. READ - DETAIL DATA KRS
# ==========================================

@app.route("/krs/<int:krs_id>", methods=["GET"])
def get_krs(krs_id):

    conn = None

    try:
        conn = get_db_connection()

        cur = conn.cursor(
            cursor_factory=RealDictCursor
        )

        cur.execute("""
            SELECT
                k.id,
                m.nim,
                m.nama,
                mk.kode_mk,
                mk.nama_mk,
                mk.sks,
                k.tahun_ajaran,
                k.semester_akademik,
                k.tanggal_pengambilan
            FROM krs k
            JOIN mahasiswa m
                ON k.mahasiswa_id = m.id
            JOIN mata_kuliah mk
                ON k.mata_kuliah_id = mk.id
            WHERE k.id = %s
        """, (krs_id,))

        row = cur.fetchone()

        cur.close()

        if not row:
            return jsonify({
                "status": "error",
                "message": "Data KRS tidak ditemukan"
            }), 404

        result = dict(row)

        if result["tanggal_pengambilan"]:
            result["tanggal_pengambilan"] = str(
                result["tanggal_pengambilan"]
            )

        return jsonify({
            "status": "success",
            "data": result
        })

    except Exception as e:
        app.logger.exception("Gagal mengambil detail KRS.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 7. CREATE - MENAMBAHKAN DATA KRS
# ==========================================

@app.route("/krs", methods=["POST"])
def create_krs():

    data = request.get_json(silent=True) or {}

    required_fields = [
        "mahasiswa_id",
        "mata_kuliah_id",
        "tahun_ajaran",
        "semester_akademik"
    ]

    if any(field not in data for field in required_fields):
        return jsonify({
            "status": "error",
            "message": "Semua field wajib diisi"
        }), 400

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO krs (
                mahasiswa_id,
                mata_kuliah_id,
                tahun_ajaran,
                semester_akademik
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
        """, (
            data["mahasiswa_id"],
            data["mata_kuliah_id"],
            data["tahun_ajaran"],
            data["semester_akademik"]
        ))

        new_id = cur.fetchone()[0]

        conn.commit()
        cur.close()

        clear_krs_cache()

        return jsonify({
            "status": "success",
            "message": "Data KRS berhasil ditambahkan",
            "id": new_id
        }), 201

    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()

        return jsonify({
            "status": "error",
            "message": "Data tidak valid atau KRS sudah terdaftar"
        }), 409

    except Exception as e:
        if conn:
            conn.rollback()

        app.logger.exception("Gagal menambahkan data KRS.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 8. UPDATE - MENGUBAH DATA KRS
# ==========================================

@app.route("/krs/<int:krs_id>", methods=["PUT"])
def update_krs(krs_id):

    data = request.get_json(silent=True) or {}

    required_fields = [
        "mahasiswa_id",
        "mata_kuliah_id",
        "tahun_ajaran",
        "semester_akademik"
    ]

    if any(field not in data for field in required_fields):
        return jsonify({
            "status": "error",
            "message": "Semua field wajib diisi"
        }), 400

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            UPDATE krs
            SET
                mahasiswa_id = %s,
                mata_kuliah_id = %s,
                tahun_ajaran = %s,
                semester_akademik = %s
            WHERE id = %s
            RETURNING id
        """, (
            data["mahasiswa_id"],
            data["mata_kuliah_id"],
            data["tahun_ajaran"],
            data["semester_akademik"],
            krs_id
        ))

        updated = cur.fetchone()

        conn.commit()
        cur.close()

        if not updated:
            return jsonify({
                "status": "error",
                "message": "Data KRS tidak ditemukan"
            }), 404

        clear_krs_cache()

        return jsonify({
            "status": "success",
            "message": "Data KRS berhasil diperbarui",
            "id": krs_id
        })

    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()

        return jsonify({
            "status": "error",
            "message": "Data tidak valid atau terjadi duplikasi KRS"
        }), 409

    except Exception as e:
        if conn:
            conn.rollback()

        app.logger.exception("Gagal memperbarui data KRS.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 9. DELETE - MENGHAPUS DATA KRS
# ==========================================

@app.route("/krs/<int:krs_id>", methods=["DELETE"])
def delete_krs(krs_id):

    conn = None

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("""
            DELETE FROM krs
            WHERE id = %s
            RETURNING id
        """, (krs_id,))

        deleted = cur.fetchone()

        conn.commit()
        cur.close()

        if not deleted:
            return jsonify({
                "status": "error",
                "message": "Data KRS tidak ditemukan"
            }), 404

        clear_krs_cache()

        return jsonify({
            "status": "success",
            "message": "Data KRS berhasil dihapus",
            "id": krs_id
        })

    except Exception as e:
        if conn:
            conn.rollback()

        app.logger.exception("Gagal menghapus data KRS.")

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if conn:
            conn.close()


# ==========================================
# 10. MENJALANKAN APLIKASI FLASK
# ==========================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
