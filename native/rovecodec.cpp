// Bounds-checked C ABI around the unmodified MRDT RoveComm v3 codec.
#include "RoveCommPacket.h"

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace {
constexpr std::size_t kMaxPayload = 8192;
constexpr std::size_t kHeaderSize = ROVECOMM_PACKET_HEADER_SIZE;
// Local application envelope: NOT a stock MRDT rover command assignment.
constexpr std::uint16_t kApplicationDataId = 60000;
constexpr std::uint8_t kByteType = manifest::DataTypes::UINT8_T;
static_assert(kHeaderSize == 6);
static_assert(sizeof(rovecomm::RoveCommData::unBytes) >= kMaxPayload + kHeaderSize);

enum Status {
    kOk = 0,
    kInvalidArgument = 1,
    kTooLarge = 2,
    kInvalidPacket = 3,
    kOutputTooSmall = 4,
    kInternalError = 5,
};
}

extern "C" int rc_encode(const std::uint8_t* payload, std::size_t payload_size,
                         std::uint8_t* output, std::size_t capacity,
                         std::size_t* written) noexcept {
    if (written == nullptr) return kInvalidArgument;
    *written = 0;
    if (payload_size > kMaxPayload) return kTooLarge;
    if ((payload_size != 0 && payload == nullptr) || output == nullptr)
        return kInvalidArgument;
    if (capacity < kHeaderSize + payload_size) return kOutputTooSmall;
    try {
        rovecomm::RoveCommPacket<std::uint8_t> packet{};
        packet.unDataId = kApplicationDataId;
        packet.unDataCount = static_cast<std::uint16_t>(payload_size);
        packet.eDataType = manifest::DataTypes::UINT8_T;
        if (payload_size != 0) packet.vData.assign(payload, payload + payload_size);
        const auto encoded = rovecomm::PackPacket<std::uint8_t>(packet);
        std::memcpy(output, encoded.unBytes, kHeaderSize + payload_size);
        *written = kHeaderSize + payload_size;
        return kOk;
    } catch (...) {
        return kInternalError;
    }
}

extern "C" int rc_decode(const std::uint8_t* packet, std::size_t packet_size,
                         std::uint8_t* output, std::size_t capacity,
                         std::size_t* written) noexcept {
    if (written == nullptr) return kInvalidArgument;
    *written = 0;
    if (packet == nullptr || output == nullptr) return kInvalidArgument;
    if (packet_size < kHeaderSize) return kInvalidPacket;
    if (packet_size > kHeaderSize + kMaxPayload) return kTooLarge;
    const auto data_id = static_cast<std::uint16_t>((packet[1] << 8) | packet[2]);
    const auto count = static_cast<std::uint16_t>((packet[3] << 8) | packet[4]);
    // Validate all header fields and exact length before calling upstream code,
    // whose generic decoder does not receive a datagram length.
    if (packet[0] != ROVECOMM_VERSION || data_id != kApplicationDataId ||
        packet[5] != kByteType || count > kMaxPayload ||
        packet_size != kHeaderSize + count)
        return kInvalidPacket;
    if (capacity < count) return kOutputTooSmall;
    try {
        rovecomm::RoveCommData data{};
        std::memcpy(data.unBytes, packet, packet_size);
        const auto decoded = rovecomm::UnpackData<std::uint8_t>(data);
        if (count != 0) std::memcpy(output, decoded.vData.data(), count);
        *written = count;
        return kOk;
    } catch (...) {
        return kInternalError;
    }
}
